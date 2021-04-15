Installation
============

It is recommended to install mercure on a Linux machine running Ubuntu Server 18.04 LTS 64bit (or newer). The installer for the Ubuntu operating system can be downloaded at https://ubuntu.com/download/server

.. note:: mercure might run on other Linux flavors as well, but the installation instructions listed on this page will likely not be applicable without modification.

Installing mercure
------------------

After finishing the Ubuntu installation procedure, the Offis DICOM toolkit (DCMTK), gcc compiler, and jq need to be installed. A user called "mercure" should be created (the adduser command will ask for a password), and the mercure installation file should be cloned using the shown Git command. By default, mercure should be installed into the home directory of the user mercure. 

Afterwards, the installation script should be executed. This will install the required Python runtime environment (Python 3.6 or higher) and create configuration files from the templates that are shipped with mercure. Finally, the included ".service" files for running the mercure modules as daemons need to be copied to the systemd folder and enabled via the "systemctl enable" command.

You can perform these steps by copying the commands listed below into a bash shell. It is assumed that you are logged in as user with sudo rights.

::

    sudo apt install build-essential -y
    sudo apt install dcmtk -y
    sudo apt install jq -y
    sudo adduser mercure
    ssh mercure@localhost
    git clone https://github.com/mercure-router/mercure.git
    cd mercure
    git checkout stable-v0.1
    cd ~/mercure/installation
    ./install.sh
    exit
    cd /home/mercure/mercure/installation
    sudo cp *.service /etc/systemd/system
    sudo systemctl enable mercure_bookkeeper.service
    sudo systemctl enable mercure_cleaner.service
    sudo systemctl enable mercure_dispatcher.service
    sudo systemctl enable mercure_receiver.service
    sudo systemctl enable mercure_router.service
    sudo systemctl enable mercure_ui.service


Creating data storage
---------------------

By default, the received DICOM files are buffered in subfolders of the directory "/home/mercure/mercure-data". The commands listed below will create the required folders in this location.

::

    ssh mercure@localhost
    mkdir mercure-data; cd mercure-data
    mkdir incoming; mkdir outgoing; mkdir success; mkdir error; mkdir discard;

.. note:: The storage location for buffering the DICOM files can also be changed. This is necessary, e.g., if a dedicated hard-drive should be used for the file buffering. In this case, the storage location needs to be updated in the configuration file mercure.json, as described below.


Installing PostgreSQL
---------------------

The bookkeeper service uses a PostgreSQL database to store all recorded data. Several steps are necessary to install and configure PostgreSQL. It is possible to use mercure also without the bookkeeper service. However, it's highly recommended to use bookkeeper, as it makes mercure much more powerful and easy to maintain. 

.. note:: The commands below create a database for the mercure data and already prepare the database for use with the Redash visualization software, as described on the Monitoring page. If Redash should not be used, all commands containing the word "redash" can be omitted. 

Keep in mind that '[mercure pwd]' in the command below needs to be replaced with the password that was entered when creating user mercure (and redash, respectively).

::

    sudo apt install postgresql postgresql-contrib -y
    sudo -i -u postgres
    createuser -P mercure
    createuser -P redash
    createdb mercure
    psql
    ALTER USER mercure WITH PASSWORD '[mercure pwd]';
    ALTER USER redash WITH PASSWORD '[redash pwd]';
    GRANT ALL PRIVILEGES ON DATABASE mercure to mercure;
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


.. note:: The commands above assign read/write rights to the user "mercure", enabling the bookkeeper service to create the required database tables and store received monitoring information in the database. However, when working with the database for data analysis, an account with read-only rights should be used to prevent accidental data modification during the analysis. This applies in particular to the created user "redash".

Read-only permissions can only be granted if the database tables already exist. The tables are automatically created when the bookkeeper service is started for the first time. Therefore, we first need to complete the mercure configuration before we can grant read-only permissions.


Basic mercure configuration
--------------------------

Before mercure can be started for the first time, several basic configuration steps are required.

First, you need to edit "webgui.env" and change the SECRET_KEY for the webgui. 

::

    ssh mercure@localhost
    cd ~/mercure/configuration
    nano webgui.env

By default, the SECRET_KEY is set to "PutSomethingRandomHere" and you need to change it to something random (it doesn't matter what exactly, just keep it a secret).

.. important:: The webgui will not start until you change the secret key.

By default, the webgui runs on port 8080. Thus, you need to enter "http://x.x.x.x:8000" into your webbrowser. If you want to run it on a different port, you can change the port in the file "webgui.env" as well.

.. note:: The Redash installation script automatically installs Redash on port :80. If you want to run the mercure webgui on port :80 instead, you first need to change the port of Redash (see instructions in the Redash installation section).

Next, you need to tell the bookkeeper the database password. This needs to be done in the file "bookkeeper.env" by replacing "ChangePasswordHere" with the password that you selected for the database user mercure:

::

    nano bookkeeper.env

.. tip:: In this file, you can also change the port that the bookkeeper listens on (8080 by default), but that is normally not needed. If you need to change it, change it also in the file "mercure.json".

Finally, if you are using a different storage location than "/home/mercure/mercure-data", then you need to update the paths in the following two files:

::

    # Change paths in lines 3-7
    nano mercure.env
    ------
    # Change line incoming=... (also change line binary=... if using other install folder)
    nano ../receiver.sh
    ------
    exit


First start of mercure
---------------------

Now, you can start mercure for the fist time. For now, start only the bookkeeper service, so that the database tables are created, and the webgui, so that the other services can later be started through the webgui.

The following commands need to be entered using a sudo account (i.e., not as user mercure):

::

    systemctl start mercure_bookkeeper.service
    systemctl start mercure_ui.service

You can validate if the two services started correctly with the following two commands:

::

    journalctl -u mercure_bookkeeper.service
    journalctl -u mercure_ui.service

In addition, you should open a web browser and test if the login page appears if you enter the server ip (with port :8000 - or the port that you selected).


Completing the PostgreSQL configuration
---------------------------------------

Now that the database tables have been created by the bookkeeper, you can grant read-only permissions to the user "redash". This can be achieved by running the following commands. 

::

    sudo -i -u postgres
    psql
    \c mercure
    GRANT CONNECT ON DATABASE mercure TO redash;
    GRANT USAGE ON SCHEMA public TO redash;
    GRANT SELECT ON ALL TABLES IN SCHEMA public TO redash;
    ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO redash;
    \q
    exit

.. important:: These commands need to be rerun whenever the database tables have been dropped (e.g., when clearing the database).


Installing Redash
-----------------

Redash is a powerful open-source web application for analyzing and visualizing data stored in SQL databases, like the data collected by the bookkeeper service. Instead of integrating limited analysis functions into mercure' own webgui, we decided to utilize Redash instead, which provides much greater flexibility. You can learn more about Redash at http://redash.io

Redash provides a convenient installation script that uses Docker for the Redash deployment. It is highly recommended to use this script, unless you are very familiar with Redash. 

::

    wget https://raw.githubusercontent.com/getredash/setup/master/setup.sh
    chmod 700 setup.sh
    sudo ./setup.sh

Open the Redash configuration page in a web browser

::

    http://[server ip]/setup

After setting up your Redash administrator password, click the top-right configuration icon and select "New Data Source". Select a PostgreSQL database and enter the following connection settings

::

    Type: Postgres
    Name: mercure
    Host: 172.17.0.1
    Port: 5432
    User: redash
    Password: [as selected above]
    Database Name: mercure

Afterwards, click "Save" and validate the database connection by clicking the button "Test Connection". If you see a green "Success" notification on the bottom-right, everything works.

.. tip:: If you want to run Redash on a different port than :80 (e.g., webgui on :80 and redash on :81), then you need to edit the file "/opt/redash/docker-compose.yml" and change the value "80:80" in the nginx section to, e.g., "81:80". Afterwards, you need to restart the  nginx container.


Congratulations
---------------

If you have made it to here, then you have mastered the installation of mercure. Everything that follows from here will be much easier.
