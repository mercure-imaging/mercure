#!/bin/bash
set -euo pipefail

echo "## Create a read-only user for Mercure..."
DB_NAME="mercure"
DB_USER="metabase_read_user"
DB_PASSWORD=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1 || true)
DB_HOST="127.0.0.1"
DB_PORT="5432"

# Connect and create the read-only user. Update the password if the user already exists.
sudo -u postgres -s <<- EOM
    psql
    \c mercure
    CREATE USER $DB_USER with encrypted password '$DB_PASSWORD';
	ALTER USER $DB_USER WITH PASSWORD '$DB_PASSWORD';
    GRANT CONNECT ON DATABASE $DB_NAME TO $DB_USER;
    GRANT USAGE ON SCHEMA public TO $DB_USER;
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO $DB_USER;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO $DB_USER;
    \q
EOM
echo "Read-only user $DB_USER created and permissions granted."
echo "DB_METABASE_USER_PASSWORD='$DB_PASSWORD'" > "/opt/mercure/config/metabase.env"

echo "## Insalling Metabase..."
sudo docker pull metabase/metabase:v0.49.7
sudo docker run -d -p 3000:3000 --name metabase --network="host" metabase/metabase:v0.49.7

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
MB_EMAIL="user@user.com"
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
			"host": "127.0.0.1",
			"port": 5432,
			"dbname": "mercure",
			"user": "'$DB_USER'",
			"password": "'$DB_PASSWORD'",
			"ssl": false
		}
	}
 }'
echo "Metabase initial setup and database connection completed."
echo -e "\n\e[1;34m=================================================== \n"
echo "Your Metabase instance is now running at http://127.0.0.1:3000"
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
if [ "$SESSION_TOKEN" == "" ]; then
    echo "Authentication failed. Check your credentials."
    exit 1
fi
echo "Session token obtained: $SESSION_TOKEN"

# Create a new API token
API_TOKEN=$(curl -s -X POST "127.0.0.1:3000/api/api-key" \
	-H "Content-Type: application/json" -H 'x-metabase-session: '$SESSION_TOKEN'' \
	-d '{"name": "API Token", "permissions": "all", "group_id": 2}' | jq -r '.unmasked_key')

# Check if token creation was successful
if [ "$API_TOKEN" == "" ]; then
    echo "Failed to create API token."
    exit 1
fi

echo "New permanent API token created and added to config: $API_TOKEN"
echo "API_TOKEN='$API_TOKEN'" >> "/opt/mercure/config/metabase.env"

# Verify the API token
# echo "Verifying the API token..."
# RESPONSE=$(curl -s -H 'x-api-key: '$API_TOKEN'' -X GET 'http://localhost:3000/api/permissions/group')
# echo $RESPONSE