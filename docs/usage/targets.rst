Targets
========

Targets define connections to external services. These are used to send and :doc:`retrieve </usage/query>` DICOMs. 

Target nodes can be defined and configured on the "Targets" page. The first page shows an overview of the currently configured targets. By clicking on an individual item, you can see the target details (e.g., IP address and port). You can test if the target can be reached by clicking the "Test" button, which will try to ping the server and check the connection.

.. image:: /images/ui/targets.png
   :width: 550px
   :align: center
   :class: border

Click the "Add New" button to create a new target. This can be done during normal operation of the server, i.e. it is not necessary to stop any of the services for adding new targets.

.. image:: /images/ui/target_edit.png
   :width: 550px
   :align: center
   :class: border

After choosing a unique name for the target, you can edit the target settings. 

.. table:: Target Types

    =========== ======= ============
    Type        Push    Pull (Query)
    =========== ======= ============
    DICOM       Y       Y
    DICOM+TLS   Y       N
    DICOMWeb    Y       Y
    Folder      Y       N (but see DICOMWeb)
    rsync       Y       N
    S3          Y       N
    SFTP        Y       N
    XNAT        Y       N
    =========== ======= ============

Direction
---------

The default direction, "push", is available on all targets. This indicates that this target can be used at a routing target. 

"pull" indicates that this target can only be used in the query interface. This should be used for services that cannot or should not be sent to, but can be queried. It is currently available on DICOM and DICOMWeb.

"both" indicates that this target can be used in both situations.

DICOM
-----

For DICOM targets, enter the parameters of the DICOM node, including the IP address, port, the target AET (application entity title) that should be called on the receiver side, and the source AET with which mercure identifies itself to the target.

.. tip:: Some DICOM nodes require that you set a specific target AET, while other systems ignore this setting. Likewise, some DICOM nodes only accept images from a sender who's source AET is known, while others ignore the value. Please check with the vendor/operator of your DICOM node which values are required.

For DICOM TLS targets, enter the TLS client key path, TLS client certificate path, and the path to the Certificate Authority (CA) certificate file. You will need to add these files to your mercure installation, e.g. in `/opt/mercure/certs`.

.. important:: Support for DICOM TLS transfers is still experimental and should be used with care.

.. important:: Due to an incompatibility in DICOM toolkit v3.6.4 and OpenSSL v1.1.1, the dcmtk and openssl versions supported by Ubuntu 20.04, only Ubuntu 22.04 mercure installs support for DICOM+TLS targets.

DICOMWeb
--------

The DICOMWeb target additionally supports querying a local folder of dicoms. To use this, specify the folder with ``file://``, eg ``file///media/dicoms``. If mercure has write permissions, it will generate a sqlite index, otherwise it will re-index it on each query. Needless to say, if the folder is too large, this would make queries very slow and resource intensive. 

Folder
------
The folder target is a folder local to Mercure. When running in Docker, this folder will be inside the dispatcher container; for this folder to be available and persist on the base system, the Docker Compose configuration will need to map this folder to a Docker volume or a folder in the base filesystem. 

The "Exclusion Filter" option is a comma-separated list of `glob expressions <https://docs.python.org/3/library/shutil.html#copytree-example>`_ which specify files to be ignored. For instance, if a processing step produces dicoms, pngs and json, ``*.png,*.json`` will skip the png and json files from being sent.

rsync
-----

The rsync connection will use certificate-based authentication if possible, but you can specify a username and password if necessary. 

If the "Execute shell command after transfer" option is set, Mercure will attempt to log in and execute a script named `mercure_complete.sh` in the target folder. The command will be executed as 

``mercure_complete.sh <destination_folder> <target_name>``

SFTP
----

For SFTP targets, enter the hostname or IP, target folder on the server, username, and password. 

.. tip:: It is recommended to create a restricted user account for the SFTP uploads. Never use the credentials of an account with access to sensitive information, as the SFTP credentials are stored in the configuration file.

.. important:: Support for SFTP transfers is still experimental and should be used with care.

Information
-----------

On the "Information" tab, you can add information for documentation purpose, including a contact e-mail address (so that it can be looked up who should be contacted if problems with the target occur) and a description of the target.

