job "mercure-ui" {
  datacenters = ["dc1"]
  type        = "service"
  
  meta {
    environment = "dev"
    runner = "nomad"
  }

  group "core" {
    network {
      mode = "bridge"
      port "http" {
        static  = 8000
        to = 8000
      }
    }
    volume "code" {
      type      = "host"
      source    = "mercure-code"
    }
    volume "config" {
      type      = "host"
      source    = "mercure-config"
    }
    volume "data" {
      type      = "host"
      source    = "mercure-data"
    }
    task "ui" {
      driver = "docker"
      env {
        MERCURE_ENV = "${NOMAD_META_environment}"
        MERCURE_RUNNER = "${NOMAD_META_runner}"
      }
      volume_mount {
        volume      = "code"
        destination = "/opt/mercure/app"
      }
      volume_mount {
        volume      = "data"
        destination = "/opt/mercure/data"
      }
      volume_mount {
        volume      = "config"
        destination = "/opt/mercure/config"
      }
      config {
        image = "mercureimaging/mercure-ui:dev"
        ports = ["http"]
      }
      resources {
        memory=128
      }
    }
  }
}