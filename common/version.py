"""
version.py
==========
Semantic version handling for mercure.
"""

# Standard python includes
import os
import daiquiri
import logging
from pathlib import Path
import common.log_helpers as log_helpers

# Create local logger instance

logger = log_helpers.get_logger()


class SemanticVersion:
    """Helper class for handling semantic versioning in mercure."""

    major = 0
    minor = 0
    patch = 0
    state = 0
    dev = 0
    version_string = ""

    STATES = ["invalid", "dev", "alpha", "beta", "rc", "stable"]
    INVALID = "0.0.0-invalid.0"

    def __init__(self) -> None:
        self.read_version_file()

    def parse_version_string(self) -> bool:
        """Checks if the version string read from the VERSION file is valid and parses it into
        numerical values stored in the object. Returns False is the version string is invalid."""

        if self.version_string == self.INVALID:
            return False

        main_ver = ""
        dev_ver = ""

        # Validate and parse version number
        if "-" in self.version_string:
            main_ver, dev_ver = self.version_string.split("-")
        else:
            main_ver = self.version_string
            self.dev = 0
            self.state = 5

        main_numbers = main_ver.split(".")
        if len(main_numbers) != 3:
            return False

        for i in main_numbers:
            if not i.isnumeric():
                return False

        self.major = int(main_numbers[0])
        self.minor = int(main_numbers[1])
        self.patch = int(main_numbers[2])

        if dev_ver:
            dev_numbers = dev_ver.split(".")
            if len(dev_numbers) != 2:
                return False
            if not (dev_numbers[0]) in self.STATES:
                return False
            self.state = self.STATES.index(dev_numbers[0])
            if not dev_numbers[1].isnumeric():
                return False
            self.dev = int(dev_numbers[1])

        return True

    def read_version_file(self) -> bool:
        """Reads the version string from the file VERSION in mercure's root folder
        and parses it. If the file is missing or invalid, the version string is
        set to '0.0.0-invalid.0' and all numerical version numbers are set to 0."""

        # Read the version string from the file VERSION in mercure's app folder
        version_filepath = os.path.dirname(os.path.realpath(__file__)) + "/../VERSION"
        version_file = Path(version_filepath)

        if not version_file.exists():
            error_message = f"Version file not found at {version_filepath}"
            logger.error(error_message)
            self.version_string = self.INVALID
        else:
            try:
                with open(version_file, "r") as version_filecontent:
                    self.version_string = version_filecontent.readline().strip()
            except:
                error_message = f"Unable to open or read file {version_filepath}"
                logger.error(error_message)
                self.version_string = self.INVALID

        # Make sure that the version string is valid and convert it to numerical values
        if not self.parse_version_string():
            error_message = f"Version string is not valid {self.version_string}"
            logger.error(error_message)
            # Invalidate the version numbers
            self.version_string = self.INVALID
            major = 0
            minor = 0
            patch = 0
            state = 0
            dev = 0

        return True

    def get_version_string(self) -> str:
        """Returns the semantic version string. If no valid version number has been found,
        it will return 0.0.0-invalid.0."""
        if not self.version_string:
            self.read_version_file()
        return self.version_string

    def get_image_tag(self) -> str:
        """Returns the image tag that should be used for pulling docker images"""
        if not self.version_string:
            self.read_version_file()

        if self.version_string == self.INVALID:
            # Use the latest image as fallback if the version number is invalid
            return "latest"
        else:
            return self.version_string

    def get_version_signature(self) -> list:
        """Returns the parsed version number as list of numerical values that can be compared
        for version consistency check."""
        return [self.major, self.minor, self.patch, self.state, self.dev]

    def is_dev_version(self) -> bool:
        """Returns True if the current version is a version under development."""
        return self.dev > 0

    def is_release(self) -> bool:
        """Returns True if the current version is a release version."""
        return self.dev == 0

    def is_valid_version(self) -> bool:
        """Returns True if the version numbering is valid."""
        return self.state != 0


# Global object storing the semantic version
mercure_version = SemanticVersion()
