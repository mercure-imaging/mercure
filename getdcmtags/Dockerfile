ARG UBUNTU_VERSION=22.04
FROM ubuntu:${UBUNTU_VERSION}
ENV DEBIAN_FRONTEND=noninteractive    
# Install necessary packages
RUN apt-get update && apt-get install -y \
    build-essential \
    qtbase5-dev \
    dcmtk \
    libdcmtk-dev \
    jq \
    && rm -rf /var/lib/apt/lists/*

# Set the working directory
WORKDIR /app

# Copy the project files into the container
COPY . .
RUN mkdir /build

# Set the default command
CMD qmake && make && ./test.sh && cp getdcmtags /build