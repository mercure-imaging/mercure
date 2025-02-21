#!/bin/bash
set -euo pipefail

INSTALL_TYPE=$1

echo "## Create a read-only user for mercure..."
DB_NAME="mercure"
DB_USER="metabase_read_user"
DB_PASSWORD=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1 || true)
DB_HOST="127.0.0.1"
DB_PORT="5432"

if [ "$INSTALL_TYPE" == "docker" ]; then
	DB_PORT="15432"
fi

# Connect and create the read-only user. Update the password if the user already exists.
create_db_user() {
	PSQL_COMMANDS="
	\\c $DB_NAME
		CREATE USER $DB_USER with encrypted password '$DB_PASSWORD';
		ALTER USER $DB_USER WITH PASSWORD '$DB_PASSWORD';
		GRANT CONNECT ON DATABASE $DB_NAME TO $DB_USER;
		GRANT USAGE ON SCHEMA public TO $DB_USER;
		GRANT SELECT ON ALL TABLES IN SCHEMA public TO $DB_USER;
		ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO $DB_USER;
	\\q"
	if [ "$INSTALL_TYPE" == "systemd" ]; then
		sudo -u postgres -s <<< "psql $PSQL_COMMANDS"
	elif [ "$INSTALL_TYPE" == "docker" ]; then
		sudo docker exec -i mercure_db_1 bash <<< "psql -U mercure -h localhost $PSQL_COMMANDS"
	fi
}
create_db_user

# verify the created user has access to the tables
export PGPASSWORD="$DB_PASSWORD"
set +e
counter=0
while true; do
	if [ "$INSTALL_TYPE" == "systemd" ]; then
		psql -U $DB_USER -h localhost $DB_NAME -c "SELECT * from tests;" > /dev/null 2>&1
	elif [ "$INSTALL_TYPE" == "docker" ]; then
		sudo docker exec mercure_db_1 psql -U $DB_USER -h localhost $DB_NAME -c "SELECT * from tests;" > /dev/null 2>&1
	fi
	if [ $? -eq 0 ]; then
		break
	fi
	if [ $counter -eq 4 ]; then
		echo "COULD NOT SET CORRECT PERMISSION FOR METABASE DB USER. ABORTING!"
		echo "Try setting the permissions manually in the psql shell and run metabase_install.sh again:"
		echo "
		GRANT CONNECT ON DATABASE $DB_NAME TO $DB_USER;
		GRANT USAGE ON SCHEMA public TO $DB_USER;
		GRANT SELECT ON ALL TABLES IN SCHEMA public TO $DB_USER;
		ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO $DB_USER;"
		exit 1
	else
		echo "METABASE DB USER DOES NOT HAVE CORRECT PERMISSION. RETRYING..."
		sleep 5
		create_db_user
	fi
	((counter++))
done
set -e
unset PGPASSWORD

echo "Read-only user $DB_USER created and permissions granted."
echo "DB_METABASE_USER_PASSWORD='$DB_PASSWORD'" > "/opt/mercure/config/metabase.env"

echo "## Installing Metabase..."
sudo docker pull metabase/metabase:v0.49.7
sudo docker run --restart=always -d -p 3000:3000 --name metabase --network="host" metabase/metabase:v0.49.7

# Retrieving metabase setup token
echo "Waiting for Metabase to start..."
while true; do
	set +e
	STATUS=$(curl -s -X GET "http://127.0.0.1:3000/api/health" | jq -r '.status')
    if [ "$STATUS" == "ok" ]; then
		echo "Metabase is up and running. Now doing initial setup..."
        break
	else
		sleep 10
	fi
	set -e
done
SETUP_TOKEN=$(curl -s -X GET "http://127.0.0.1:3000/api/session/properties" | jq -r '.["setup-token"]')

# Setting up metabase
MB_EMAIL="admin@mercure.local"
MB_PASSWORD=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1 || true)
curl -s -X POST "http://localhost:3000/api/setup" -H "Content-Type: application/json" -d '{ 
	"token": "'$SETUP_TOKEN'",
	"prefs": {
		"site_name": "My Metabase Instance",
		"allow_tracking": false
	},
	"user": {
		"first_name": "Admin",
		"last_name": "User",
		"email": "'$MB_EMAIL'",
		"password": "'$MB_PASSWORD'"
	},
	"database": {
		"engine": "postgres",
		"name": "Mercure Database",
		"details": {
			"host": "'$DB_HOST'",
			"port": "'$DB_PORT'",
			"dbname": "'$DB_NAME'",
			"user": "'$DB_USER'",
			"password": "'$DB_PASSWORD'",
			"ssl": false
		}
	}
 }'
echo "Metabase initial setup and database connection completed."
echo -e "\n\e[1;34m=================================================== \n"
echo "Your Metabase instance is now running at http://127.0.0.1:3000"
echo "(Check port forwarding using 'vagrant port' if using Vagrant and port occupied.)"
echo "Login with the following credentials:"
echo "Email: $MB_EMAIL"
echo "Password: $MB_PASSWORD"
echo -e "\n=================================================== \e[0m\n"
echo "MB_PASSWORD='$MB_PASSWORD'" >> "/opt/mercure/config/metabase.env"

# Create a permanent token for future use.
# Authenticate and get the session token.
SESSION_TOKEN=$(curl -s -X POST "127.0.0.1:3000/api/session" \
	-H "Content-Type: application/json" \
	-d '{"username": "'"$MB_EMAIL"'", "password": "'"$MB_PASSWORD"'"}' | jq -r '.id')

# Check if authentication was successful
if [ "$SESSION_TOKEN" == "" ] || [ "$SESSION_TOKEN" == "null" ]; then
    echo "Authentication failed. Check your credentials."
    exit 1
fi
echo "Session token obtained."

# Create a new API token
API_TOKEN=$(curl -s -X POST "127.0.0.1:3000/api/api-key" \
	-H "Content-Type: application/json" -H 'x-metabase-session: '$SESSION_TOKEN'' \
	-d '{"name": "API Token", "permissions": "all", "group_id": 2}' | jq -r '.unmasked_key')

# Check if token creation was successful
if [ "$API_TOKEN" == "" ] || [ "$API_TOKEN" == "null" ]; then
    echo "Failed to create API token."
    exit 1
fi

echo "New permanent API token created and added to config: $API_TOKEN"
echo "API_TOKEN='$API_TOKEN'" >> "/opt/mercure/config/metabase.env"

# Verify the API token
# echo "Verifying the API token..."
# RESPONSE=$(curl -s -H 'x-api-key: '$API_TOKEN'' -X GET 'http://localhost:3000/api/permissions/group')
# echo $RESPONSE

echo "Importing mercure Metabase dashboard..."

git clone --depth 1 -b fix https://github.com/mercure-imaging/metabase_export_import.git

if [ "$INSTALL_TYPE" == "systemd" ]; then
	/opt/mercure/env/bin/python3 metabase_export_import/metabase_import.py \
	"http://127.0.0.1:3000/api/" $MB_EMAIL $MB_PASSWORD \
	"Mercure Database" exported_dashboard "Mercure Collection"
elif [ "$INSTALL_TYPE" == "docker" ]; then
	python3 metabase_export_import/metabase_import.py \
	"http://127.0.0.1:3000/api/" $MB_EMAIL $MB_PASSWORD \
	"Mercure Database" exported_dashboard "Mercure Collection"
fi

echo "Metabase dashboard imported successfully."