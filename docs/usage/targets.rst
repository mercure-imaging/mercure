Targets
========

Target nodes that should receive processed and routed DICOM series (via DICOM, DICOM+TLS or SFTP connection) can be defined and configured on the "Targets" page. The first page shows an overview of the currently configured targets. By clicking on an individual item, you can see the target details (e.g., IP address and port). You can test if the target can be reached by clicking the "Test" button, which will try to ping the server and open a connection (via C-Echo or SFTP).

.. image:: /images/ui/targets.png
   :width: 550px
   :align: center
   :class: border

Click the "Add New" button to create a new target. This can be done during normal operation of the server, i.e. it is not necessary to stop any of the services for adding new targets.

.. image:: /images/ui/target_edit.png
   :width: 550px
   :align: center
   :class: border

After choosing a unique name for the target, you can edit the target settings. First, you need to select the type of target. Currently, DICOM targets and SFTP targets are supported (other target types, such as DICOMweb, will be added at later time).

For DICOM targets, enter the parameters of the DICOM node, including the IP address, port, the target AET (application entity title) that should be called on the receiver side, and the source AET with which mercure identifies itself to the target.

.. tip:: Some DICOM nodes require that you set a specific target AET, while other systems ignore this setting. Likewise, some DICOM nodes only accept images from a sender who's source AET is known, while others ignore the value. Please check with the vendor/operator of your DICOM node which values are required.

For SFTP targets, enter the hostname or IP, target folder on the server, username, and password. 

.. tip:: It is recommended to create a restricted user account for the SFTP uploads. Never use the credentials of an account with access to sensitive information, as the SFTP credentials are stored in the configuration file.

.. important:: Support for SFTP transfers is still experimental and should be used with care.

For DICOM TLS targets, enter the TLS client key path, TLS client certificate path, and the path to the Certificate Authority (CA) certificate file. You will need to add these files to your mercure installation, e.g. in `/opt/mercure/certs`.

.. important:: Support for DICOM TLS transfers is still experimental and should be used with care.

.. important:: Due to an incompatibility in DICOM toolkit v3.6.4 and OpenSSL v1.1.1, the dcmtk and openssl versions supported by Ubuntu 20.04, only Ubuntu 22.04 mercure installs support for DICOM+TLS targets.

On the "Information" tab, you can add information for documentation purpose, including a contact e-mail address (so that it can be looked up who should be contacted if problems with the target occur) and a description of the target.

