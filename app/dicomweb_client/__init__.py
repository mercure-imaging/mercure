from dicomweb_client.api import DICOMwebClient, DICOMfileClient
from dicomweb_client.protocol import DICOMClient
from dicomweb_client.uri import URI, URISuffix, URIType

# MERCURE PATCH: this copy is not pip-installed, so importlib.metadata would report either
# '0.0.0' or the version of an unrelated installed dicomweb-client distribution.
__version__ = '0.60.1'

__all__ = [
    'DICOMClient',
    'DICOMfileClient',
    'DICOMwebClient',
    'URI',
    'URISuffix',
    'URIType',
]
