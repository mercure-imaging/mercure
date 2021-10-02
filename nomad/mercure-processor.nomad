
job "mercure-processor" {
  datacenters = ["dc1"]
  type        = "batch"

  parameterized  {
    meta_required = ["IMAGE_ID", "PATH"]
  }

  group "core" {
    service {
      name = "processor"
      connect {
        sidecar_service {
          proxy {
            upstreams {
              destination_name = "storage"
              local_bind_port  = 5000
            }
          }
        }
      }
    }
    network {
      mode = "bridge"
    }
    volume "keys" {
      type      = "host"
      source    = "processor-keys"
    }
    task "setup" {
      driver = "docker"
      config {
        image = "mercureimaging/processor:dev"
        command = "./docker-entrypoint.sh"
        args = ["-m", "in"]
      }
      lifecycle {
        hook    = "prestart"
        sidecar = false
      }
      volume_mount {
        volume      = "keys"
        destination = "${ NOMAD_SECRETS_DIR }/keys"
      }
      env {
        // STORAGE_IP = "10.0.2.15"
        STORAGE_IP = "${NOMAD_UPSTREAM_IP_storage}"
        // STORAGE_PORT = "3000" 
        STORAGE_PORT = "${NOMAD_UPSTREAM_PORT_storage}"
      }
    }
    task "process" {
      driver = "docker"
      config {
        image = "${NOMAD_META_IMAGE_ID}"
      }
      env {
        MERCURE_IN_DIR = "${ NOMAD_ALLOC_DIR }/data/in"
        MERCURE_OUT_DIR = "${ NOMAD_ALLOC_DIR }/data/out"
      }
    }

    // task "mock-service" {
    //   driver = "docker"

    //   config {
    //     image   = "mercureimaging/processor:dev"
    //     command = "bash"
    //     args    = ["-c", "echo The service is running! && while true; do sleep 2; done"]
    //     network_mode = "host"
    //   }
    //   volume_mount {
    //     volume      = "keys"
    //     destination = "${ NOMAD_SECRETS_DIR }/keys"
    //   }
    //   env {
    //     STORAGE_IP = "${NOMAD_UPSTREAM_IP_storage}"
    //     STORAGE_PORT = "${NOMAD_UPSTREAM_PORT_storage}"
    //   }

    // }

    task "takedown" {
      driver = "docker"
      config {
        image = "mercureimaging/processor:dev"
        command = "./docker-entrypoint.sh"
        args = ["-m", "out"]
      }
      volume_mount {
        volume      = "keys"
        destination = "${ NOMAD_SECRETS_DIR }/keys"
      }
      env {
        // STORAGE_IP = "10.0.2.15"
        STORAGE_IP = "${NOMAD_UPSTREAM_IP_storage}"
        // STORAGE_PORT = "3000" 
        STORAGE_PORT = "${NOMAD_UPSTREAM_PORT_storage}"
      }
    }
  }
}
