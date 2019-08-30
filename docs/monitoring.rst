Monitoring
==========

Hermes provides three different mechanisms for monitoring the router activity and health.

Log files
---------

All Hermes services write detailed logging information with timestamps into system log files. The most convenient way to review these logs is to use the "Logs" page of the Hermes web interface. Here you can see a separate tab for every service. The logs are updated whenever you switch between tabs and when you click the refresh button on the top-right.

Using the From/To controls, you can limit the time span that is shown in the log viewer.

.. note:: Only the last 1000 lines of each log are displayed to keep the user interface responsive. If you are looking for an older event, use the From/To fields to narrow down the time span.

.. tip:: The log files can also be viewed in the terminal using the journalctl command by providing the service name as argument. For example, "journalctl -u hermes_ui.service" shows the log of the webgui. You can see the names of the different services as tooltip when hovering over the tabs on the "Logs" page.


Graphite
--------

`Graphite <https://graphiteapp.org/>`_ is a very powerful tool for monitoring the health of a server. It can collect time-series data from various sources and stores the data in a database. Instead of displaying the data directly with Graphite, the collected data is often visualized using `Grafana <https://grafana.com/>`_, which makes it very easy to create dashboards for various data sources and to setup alerts. 

We highly recommend that you monitor your Hermes server with Graphite and Grafana. In a typical setup, Graphite and Grafana are running on a separate monitoring server. Basic health parameters like the available disk space, CPU load, and memory usage can be collected by installing the `collectd <https://collectd.org/>`_ service on your server, which will transmit the information to your Graphite instance. 

Hermes can transmit additional information about its activities to Graphite. To enable it, shutdown all Hermes services and edit the keys graphite_ip and graphite_port in the file hermes.json (here you need to enter the IP and port of your Graphite instance). Afterwards, restart the Hermes services.

Hermes transmits the following information to Graphite:

====================================== ===========================================================================
Key                                    Meaning
====================================== ===========================================================================
hermes.router.main.incoming.series     Number series in the incoming folder waiting for completion
hermes.router.main.incoming.files      Number of received DICOM files waiting in the incoming folder
hermes.router.main.events.run          Triggered when the router checks for incoming files (value=1)
hermes.router.main.events.boot         Triggered when the router is started (value=1)
hermes.router.main.events.shutdown     Triggered when the router shuts down (value=1)
hermes.dispatcher.main.events.run      Triggered when the dispatcher checks for outgoing series (value=1)
hermes.dispatcher.main.events.boot     Triggered when the dispatcher is started (value=1)
hermes.dispatcher.main.events.shutdown Triggered when the dispatcher shuts down (value=1)
hermes.cleaner.main.events.run         Triggered when the cleaner checks for files to-be-deleted (value=1)
hermes.cleaner.main.events.boot        Triggered when the cleaner is started (value=1)
hermes.cleaner.main.events.shutdown    Triggered when the cleaner shuts down (value=1)
====================================== ===========================================================================

By creating a visualization of the hermes.x.main.events.run events, you can monitor that all processes are active and responsive.

.. tip:: If you have an advanced installation with multiple instances of the router, dispatcher, or cleaner services, it is necessary to name the individual instances (e.g., instance1 & instance2 instead of main). This can be done by providing a name as command-line argument when starting the services (thus, this needs to be configured in the systemd startup scripts).

The most convenient way for installing Graphite and Grafana is using `Docker Compose <https://docs.docker.com/compose/>`_. Below, you can see a template for docker-compose.yml file for installing both tools. Note that you need to replace the values [...] with your own information.

::

    version: "3"
    services:
    grafana:
        image: grafana/grafana
        container_name: grafana
        restart: always
        ports:
        - "3000:3000"
        networks:
        - grafana-net
        volumes:
        - grafana-storage:/var/lib/grafana
        environment:
        - GF_INSTALL_PLUGINS=[add plugins if you want]

    graphite:
        image: graphiteapp/graphite-statsd
        container_name: graphite
        restart: always
        ports:
        - "2003-2004:2003-2004"
        - "2023-2024:2023-2024"
        - "8125:8125/udp"
        - "8126:8126"
        networks:
        - grafana-net
        volumes:
        - /[install path]/configs:/opt/graphite/conf
        - /[install path]/data:/opt/graphite/storage
        - /[install path]/statsd_config:/opt/statsd/config

    networks:
    grafana-net:

    volumes:
    grafana-storage:
        external: true


Bookkeeer with Redash
---------------------

.. note:: This section is coming soon.


Setting alerts
--------------

.. note:: This section is coming soon.
