Installation
============

It is recommended to install mercure on a Linux machine running Ubuntu Server 20.04 LTS 64bit (or newer). The installer for the Ubuntu operating system can be downloaded at https://ubuntu.com/download/server

.. note:: mercure might run on other Linux distributions as well, but the installation script will not work without modification. When trying to install mercure on other Linux distributions, it might be best to focus on a Docker-based installation and derive a custom installation script from the script included in the repository.

.. warning:: mercure servers and the web-based user interface should never be placed on the internet! mercure has been designed for use in intranet environments that are secured against unauthorized access. It has not been hardened and tested for installation on the public internet. Also, DICOM transfers should never be made over the public internet (unless encrypted and secured transfer protocols are used, e.g. based on  DICOMweb).


Installation types
------------------

mercure can be installed in three different ways: 

* Using systemd as service runner
* Using Docker as service runner
* Using Nomad for orchestrating the services

Which installation type should you choose? It depends on the use case. For normal users, either a Docker-based or systemd-based installation is best suited. A systemd-based installation might have a small performance advantage, while a Docker-based installation will be easier to upgrade to newer mercure versions. If you are planning to actively develop and customize mercure, a systemd-based installation should be preferred.

With both systemd- and Docker-based installations, processing modules are executed sequentially, i.e. the requested processing module is launched inside a Docker container and the processor service waits until the processing has finished. With a Nomad-based installation, multiple processing modules can be executed in parallel. In this case, the processor service launches processing modules asynchronously and fetches  results from the processing containers when the processing has finished. Moreover, the processor can distribute the processing jobs across multiple compute nodes, i.e. you can operate a processing cluster. This might be important if you are planning to integrate computationally demanding processing algorithms and if you are expecting a large volume of processing jobs. It is also relevant if you are planning to operate processing modules with different hardware requirements, because the Nomad-based solution allows defining resource requirements for jobs. However, these functions may not be needed in many situations. Nomad-based installations are more complex and intended for advanced users.


Installing mercure
------------------

After deciding on the type of mercure installation, open a terminal shell of your Ubuntu installation for a user with sudo rights. Clone the mercure repository into the home folder of the user by typing the commands below. This will install the latest stable version, which is recommended. If you would like to install a specific version instead, replace "latest-stable" with the desired version tag. A list of all released versions can be `found here <https://github.com/mercure-imaging/mercure/releases>`_.

::

    cd ~
    git clone --branch latest-stable https://github.com/mercure-imaging/mercure.git
    cd mercure

Call the installation script and put the installation type as argument ("systemd" or "docker" or "nomad"):

::

    sudo ./install.sh systemd

The script will now perform all relevant installation steps, including installation of Docker and Python runtime environments. It will also create the user "mercure", which will be used for running the mercure processes. 

.. tip:: When installing mercure in Docker mode, the option "-b" can be used to enforce that the docker containers are rebuilt (instead of downloaded from Docker Hub). This might be helpful if you are interested in new features that have not been published as release yet. Moreover, the option "-d" selects the development version instead of the stable version.

Locations
---------

By default, mercure is installed in the folder **/opt/mercure**. If necessary, the location can be changed after the installation (see note below), but this is not recommended. The installer will always use the default path.

========================================= ==================================
Folder                                    Content
========================================= ==================================
/opt/mercure                              Base installation folder
/opt/mercure/app                          Application source code
/opt/mercure/config                       Configuration files
/opt/mercure/data                         Folders for buffering images
/opt/mercure/db                           Database of the bookkeeper
========================================= ==================================

.. note:: If you need to change the installation location, set the environment variable MERCURE_CONFIG_FOLDER to the new location where the configuration files can be found. Then, change the paths of the data folders in the configuration file mercure.json. Finally, change the application startup scripts depending on your installation type. In the case of a systemd installation, this means adjusting mercure's .service files found in the folder /etc/systemd/system.

.. tip:: The source code located in the /app folder is directly executed only for systemd-type installations. Docker and Nomad installations execute container images instead. By default, these images are downloaded from Docker Hub. If you want to modify the mercure source code, you need to rebuild the container images for the changes to go into effect. This can be done with the script build-docker.sh.

DICOM over TLS Receiver Mode
----------------------------

.. important:: Support for DICOM+TLS receiver mode is still experimental and should be used with care.

The following environment variables must be defined to run Mercure in TLS receiver mode. First, set `MERCURE_TLS_ENABLED` to `1` in order to tell Mercure to run the receiver in TLS mode. Next, specify the paths to your server TLS key, certificate and CA certificate, as shown in the below example configuration.

========================================= =====================================
Environment Variable                      Example Value
========================================= =====================================
MERCURE_TLS_ENABLED                       1
MERCURE_TLS_KEY                           /opt/mercure/certs/private_key.pem
MERCURE_TLS_CERT                          /opt/mercure/certs/certificate.pem
MERCURE_TLS_CA_CERT                       /opt/mercure/certs/CA_certificate.pem
========================================= =====================================

.. important:: The following example shows how to create your own Certificate Authority (CA) to self-sign your own certificates. In production, it may make sense to utilize your organization's certificate authority to sign your TLS receiver certificates instead, or create your CA as an intermediate CA from your organizational CA.

Here are some steps to create a simple, self-signed certificate authority and TLS key/certificate keypair that can be used to start Mercure in TLS receiver mode.

* Step 1: Generate the CA key: `openssl genrsa -out CA_key.pem 4096`
* Step 2: Create the CA certificate: `openssl req -new -x509 -days 3650 -key CA_key.pem -out CA_certificate.pem`
* Step 3: Create a TLS private key: `openssl genrsa -out SCP_private_key.pem 4096`
* Step 4: Create a CSR (Certificate Signing Request) with the TLS private key: `openssl req -new -key private_key.pem -out receiver_csr.pem`
* Step 5: Sign the CSR with the CA private key and certificate to generate the TLS certificate: `openssl x509 -req -days 3650 -in receiver_csr.pem -CA CA_certificate.pem -CAkey CA_key.pem -CAcreateserial -out certificate.pem`
* Step 6: Verify that the generated TLS certificate is valid against the CA certificate: `openssl verify -CAfile CA_certificate.pem certificate.pem`

.. tip:: When creating the CSR, ensure that the CSR common name is NOT the same as the CA common name. If so, the openssl certificate validation will fail and you will not be able to receive DICOM over TLS.

.. note:: Remember to add both your TLS receiver private key (private_key.pem), certificate file (certificate.pem) and CA certificate file (CA_certificate.pem) to the file system of your Mercure installation and specify the above environment variables to enable TLS receiver mode.

Congratulations
---------------

If you have made it to here, then you have mastered the installation of mercure. You should now be able to access mercure's user interface with a web browser by entering your server's IP address and adding :8000 (e.g., 192.168.56.1:8000). 

.. tip:: You can change the port used for the web interface from 8000 to another port by editing the file webgui.env in mercure's configuration folder. Make sure to restart the webgui service afterwards. Also, if running Docker or Nomad (or testing mercure with Vagrant), make sure to modify the port mapping to the host system as well.
