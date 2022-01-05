Advanced Topics
===============

Scaling services
----------------

By default, mercure uses only a single instance of each service module (i.e., in the case of the dispatcher, only one series per time is sent outwards), which provides sufficient performance for most applications. However, for very demanding applications with high volume of incoming DICOM series, it can be necessary run multiple instances of the modules (router, processor, dispatcher). All mercure modules have been written to allow for parallel execution, so that additional instances can be started. 

The exact way of scaling up services depends on the type of mercure installation (systemd / Docker / Nomad). The instructions below describe how services can be duplicated when using systemd (which is preferred for high-performance installations).
    
For systemd installations, the file "services.json" in the folder "/opt/mercure/config" needs to be modified. Here, the section of each module that should be scaled needs to be duplicated. For example, for scaling the dispatcher, the "dispatcher" section needs to be duplicated and a unique name needs to be selected for the copy (for the section name and inner keys "name" and "systemd_service", as shown below):
::

    {
        ...
        "dispatcher": {
            "name": "Dispatcher",
            "systemd_service": "mercure_dispatcher.service",
            "docker_service": "mercure_dispatcher_1"
        },
        "dispatcher2": {
            "name": "Dispatcher2",
            "systemd_service": "mercure_dispatcher2.service",
            "docker_service": "mercure_dispatcher_2"
        },
        ...
    }

.. note:: It is not necessary to scale the receiver module, as the receiver automatically launches a separate process for every DICOM connection.

Afterwards, the .service files of the scaled service modules need to be duplicated in the folder /etc/systemd/system. For example, if duplicating the dispatcher module as shown above, copy the existing file mercure_dispatcher.service and name it mercure_dispatcher2.service (or whatever has been listed in the file services.json). Enable and start the duplicated service by calling (from an account with sudo rights):
::

  sudo systemctl enable mercure_dispatcher2.service
  sudo systemctl start mercure_dispatcher2.service

As last step, it is necessary to authorize the mercure system user to control the duplicated services. This is done by editing the file /etc/sudoers.d/mercure (using a user account with sudo permission) and adding a line for each duplicated service (according to the name specified above). When copying an existing line from the file, make sure to change every occurrence of the service name in the line.



.. important:: The following sections are still being updated for mercure version 0.2.

Configuration files
-------------------

mercure stores the configuration in multiple files in the subfolder /configuration. If you want to backup the configuration or install mercure on another machine, you need to copy all files inside this folder.

============== ================
File           Meaning
============== ================
bookkeeper.env Contains the IP, port, and DB password for the bookkeeper
mercure.json    Configured targets, rules, storage location, and other mercure settings
services.json  Customizable list of used mercure services
users.json     User information for the webgui
webgui.env     Contains the IP, port, and secret key for the webgui
============== ================


Additional settings
-------------------

Advanced settings can be reviewed and adjusted on the Configuration page of the webgui. To change the settings, click the "Edit Settings" button at the bottom of the page. Once saved, the different service modules will automatically load the updated configuration. 

.. important:: Make sure to preserve correct JSON formatting of the settings. The webgui will automatically check the syntax before saving the file.

Alternatively to using the webgui, the changes can also be made by directly editing the file mercure.json with a Linux text editor, e.g. nano.

.. important:: When editing the configuration file directly, it is required to shutdown all mercure services prior to making any changes (via the webgui or systemctl command).

The following settings can be customized (default values can be found in default_mercure.json):

======================== ===========================================================================
Key                      Meaning
======================== ===========================================================================
incoming_folder          Buffer location for received DICOM files
outgoing_folder          Buffer location for series to be dispatched
success_folder           Storage location for sent series until retention period has passed
error_folder             Storage location for files that could not be parsed or dispatched
discard_folder           Storage location for discarded series until retention period has passed
bookkeeper               IP and port of the bookkeeper instance
graphite_ip              IP address of the graphite server. Leave empty if none
graphite_port            Port of the graphite server
router_scan_interval     Interval how often the router checks for arrived images (in sec)
series_complete_trigger  Time after arrival of last slice when series is considered complete (in sec)
dispatcher_scan_interval Interval how often the dispatcher checks for series to be sent (in sec)
retry_delay              Delay before retrying to dispatch series after failure (in sec)
retry_max                Maximum number of retries when dispatching
cleaner_scan_interval    Interval how often the cleaner checks for files to be deleted (in sec)
retention                Duration how long files will be kept before deletion (in sec)
offpeak_start            Start of the off-peak work hours (in 24h format)
offpeak_end              End of the off-peak work hours (in 24h format)  
targets                  Configured targets - should be edited via webgui
rules                    Configured rules - should be edited via webgui 
======================== ===========================================================================


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


