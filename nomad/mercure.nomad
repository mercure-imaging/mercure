job "mercure" {
  datacenters = ["dc1"]
  type        = "service"
  
  meta {
    environment = "dev"
    runner = "nomad"
  }

  group "core" {
    service {
      name = "storage"
      port = 22
      connect {
        sidecar_service {}
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
    volume "db-data" {
      type      = "host"
      source    = "mercure-db"
    }
    network {
      mode = "bridge"
      port "bookkeeper" {
        static  = 8080
        to = 8080
      }
      port "postgres" {
        static  = 5432
        to = 5432
      }
      port "dicom-receive" {
        static  = 104
        to = 1040
      }
      port "sshd" {
        static  = 3000
        to = 22
      }
    }
    task "receiver" {
      driver = "docker"
      env {
        MERCURE_ENV = "${NOMAD_META_environment}"
        MERCURE_RUNNER = "${NOMAD_META_runner}"
        MERCURE_LOG_LEVEL = "${NOMAD_META_log_level}"
        MERCURE_CONFIG_FOLDER = "/opt/mercure/config"
      }
      volume_mount {
        volume      = "config"
        destination = "/opt/mercure/config"
      }
      volume_mount {
        volume      = "data"
        destination = "/opt/mercure/data"
      }
      config {
        image = "mercureimaging/mercure-receiver:latest"
        ports = ["dicom"]
      }
      resources {
        memory=128
      }
    }
    task "cleaner" {
      driver = "docker"
      env {
        MERCURE_ENV = "${NOMAD_META_environment}"
        MERCURE_RUNNER = "${NOMAD_META_runner}"
        MERCURE_LOG_LEVEL = "${NOMAD_META_log_level}"
        MERCURE_CONFIG_FOLDER = "/opt/mercure/config"
      }
      volume_mount {
        volume      = "code"
        destination = "/opt/mercure/app"
      }
      volume_mount {
        volume      = "config"
        destination = "/opt/mercure/config"
      }
      volume_mount {
        volume      = "data"
        destination = "/opt/mercure/data"
      }
      config {
        image = "mercureimaging/mercure-cleaner:latest"
      }
    }
    task "dispatcher" {
      driver = "docker"
      env {
        MERCURE_ENV = "${NOMAD_META_environment}"
        MERCURE_RUNNER = "${NOMAD_META_runner}"
        MERCURE_LOG_LEVEL = "${NOMAD_META_log_level}"
        MERCURE_CONFIG_FOLDER = "/opt/mercure/config"
      }
      volume_mount {
        volume      = "code"
        destination = "/opt/mercure/app"
      }
      volume_mount {
        volume      = "config"
        destination = "/opt/mercure/config"
      }
      volume_mount {
        volume      = "data"
        destination = "/opt/mercure/data"
      }
      config {
        image = "mercureimaging/mercure-dispatcher:latest"
      }
      resources {
        memory=128
      }
    }
    task "router" {
      driver = "docker"
      env {
        MERCURE_ENV = "${NOMAD_META_environment}"
        MERCURE_RUNNER = "${NOMAD_META_runner}"
        MERCURE_LOG_LEVEL = "${NOMAD_META_log_level}"
        MERCURE_CONFIG_FOLDER = "/opt/mercure/config"
      }
      volume_mount {
        volume      = "code"
        destination = "/opt/mercure/app"
      }
      volume_mount {
        volume      = "config"
        destination = "/opt/mercure/config"
      }
      volume_mount {
        volume      = "data"
        destination = "/opt/mercure/data"
      }      
      config {
        image = "mercureimaging/mercure-router:latest"
      }
      resources {
        memory=128
      }
    }
    task "processor" {
      driver = "docker"
      env {
        MERCURE_ENV = "${NOMAD_META_environment}"
        MERCURE_RUNNER = "${NOMAD_META_runner}"
        MERCURE_LOG_LEVEL = "${NOMAD_META_log_level}"
        MERCURE_CONFIG_FOLDER = "/opt/mercure/config"
      }
      volume_mount {
        volume      = "code"
        destination = "/opt/mercure/app"
      }
      volume_mount {
        volume      = "config"
        destination = "/opt/mercure/config"
      }
      volume_mount {
        volume      = "data"
        destination = "/opt/mercure/data"
      }
      config {
        image = "mercureimaging/mercure-processor:latest"
      }
      resources {
        memory=128
      }
    }
    task "sshd" {
      driver = "docker"
      template {
        data = "SSHPUBKEY"
        destination = "local/ssh/authorized_keys"
      }
      config {
        image = "mercureimaging/alpine-sshd:latest"
        ports = ["sshd"]
        mount {
          type   = "bind"
          source = "local/ssh"
          target = "/home/mercure/.ssh"
        }
      }
      lifecycle {
        hook    = "prestart"
        sidecar = true
      }
      volume_mount {
        volume      = "data"
        destination = "/data"
      }
    }
    task "db" {
      driver = "docker"
      config {
        image = "library/postgres:alpine"
        ports = ["postgres"]
      }
      lifecycle {
        hook    = "prestart"
        sidecar = true
      }
      volume_mount {
        volume      = "db-data"
        destination = "/var/lib/postgresql/data"
      }
      env {
        POSTGRES_PASSWORD = "ChangePasswordHere"
        POSTGRES_USER = "mercure"
        POSTGRES_DB = "mercure"
        PGDATA = "/var/lib/postgresql/data/pgdata"
      }
    }
    task "bookkeeper" {
      driver = "docker"
      config {
        image = "mercureimaging/mercure-bookkeeper:latest"
        ports = ["bookkeeper"]
      }     
      lifecycle {
        hook    = "prestart"
        sidecar = true
      }
      volume_mount {
        volume      = "config"
        destination = "/opt/mercure/config"
      }
      volume_mount {
        volume      = "data"
        destination = "/opt/mercure/data"
      }
      env {
        DATABASE_URL = "postgresql://mercure@localhost"
        MERCURE_ENV = "${NOMAD_META_environment}"
        MERCURE_RUNNER = "${NOMAD_META_runner}"
        MERCURE_LOG_LEVEL = "${NOMAD_META_log_level}"
        MERCURE_CONFIG_FOLDER = "/opt/mercure/config"
      }
      resources {
        memory=128
      }
    }
  }
}
