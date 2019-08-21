Installation Steps
==================

Installing Hermes
-----------------

::

    sudo apt install build-essential -y
    sudo apt install dcmtk -y
    sudo adduser hermes
    ssh hermes@localhost
    git clone https://github.com/hermes-router/hermes.git
    cd ~/hermes/installation
    ./install.sh
    exit
    cd /home/hermes/hermes/installation
    sudo cp *.service /etc/systemd/system
    sudo systemctl enable hermes_bookkeeper.service
    sudo systemctl enable hermes_cleaner.service
    sudo systemctl enable hermes_dispatcher.service
    sudo systemctl enable hermes_receiver.service
    sudo systemctl enable hermes_router.service
    sudo systemctl enable hermes_ui.service


Create data storage
-------------------

::

    ssh hermes@localhost
    mkdir hermes-data; cd hermes-data
    mkdir incoming; mkdir outgoing; mkdir success; mkdir error; mkdir discard;


Installing Postgresql
---------------------

::

    sudo apt install postgresql postgresql-contrib -y
    sudo -i -u postgres
    createuser -P hermes
    createuser -P redash
    createdb hermes
    psql
    ALTER USER hermes WITH PASSWORD '[hermes pwd]';
    ALTER USER redash WITH PASSWORD '[redash pwd]';
    GRANT ALL PRIVILEGES ON DATABASE hermes to hermes;
    \c hermes
    GRANT CONNECT ON DATABASE hermes TO redash;
    GRANT USAGE ON SCHEMA public TO redash;
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO redash;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO redash;
    \q
    exit
    ------
    sudo nano /etc/postgresql/10/main/pg_hba.conf

    # Add the following line to file:
        host    all             all             172.16.0.0/12           md5
    ------
    sudo nano /etc/postgresql/10/main/postgresql.conf

    # Uncomment and add 172.17.0.1 to the following line to file:
        listen_addresses = 'localhost, 172.17.0.1' # what IP address(es) to listen on;
    ------
    sudo service postgresql restart


Installing Redash
-----------------

::

    wget https://raw.githubusercontent.com/getredash/redash/master/setup/setup.sh
    chmod 700 setup.sh
    sudo ./setup.sh

Open redash configuration page::

    http://[server ip]:5000/setup

Configure datasource using the settings::

    Type: Postgres
    Name: Hermes
    Host: 172.17.0.1
    Port: 5432
    User: redash
    Password: [as selected above]
    Database Name: hermes

Save and test connection

Adapting configuration files
----------------------------

* Change SECRET_KEY in webgui.env (change port and host if needed)
* Change database password in bookkeeper.env (change port and host if needed)
* Change installation paths in hermes.json if needed
