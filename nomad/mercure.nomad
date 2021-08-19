job "mercure" {
  datacenters = ["dc1"]
  type        = "service"
    
  group "core" {

    service {
      name = "storage"
      port = 22
      connect {
        sidecar_service {}
      }
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
      port "http" {
        static  = 8000
        to = 8000
      }
      port "postgres" {
        static  = 5432
        to = 5432
      }
      port "dicom" {
        static  = 104
        to = 104
      }
      port "sshd" {
        static  = 3000
        to = 22
      }
    }

    task "ui" {
      driver = "docker"

      volume_mount {
        volume      = "config"
        destination = "/home/mercure/mercure/configuration"
      }

      config {
        image = "yarra/mercure-ui:dev"
        ports = ["http"]
      }

      resources {
        memory=128
      }
    }
    task "receiver" {
      driver = "docker"

      volume_mount {
        volume      = "config"
        destination = "/home/mercure/mercure/configuration"
      }
      volume_mount {
        volume      = "data"
        destination = "/home/mercure/mercure-data"
      }
      config {
        image = "yarra/mercure-receiver:dev"
        ports = ["dicom"]
      }

      resources {
        memory=128
      }
    }

    task "dispatcher" {
      driver = "docker"

      volume_mount {
        volume      = "config"
        destination = "/home/mercure/mercure/configuration"
      }
      volume_mount {
        volume      = "data"
        destination = "/home/mercure/mercure-data"
      }
      config {
        image = "yarra/mercure-dispatcher:dev"
        ports = ["dicom"]
      }

      resources {
        memory=128
      }
    }
    task "router" {
      driver = "docker"

      volume_mount {
        volume      = "config"
        destination = "/home/mercure/mercure/configuration"
      }
      volume_mount {
        volume      = "data"
        destination = "/home/mercure/mercure-data"
      }
      config {
        image = "yarra/mercure-router:dev"
        ports = ["dicom"]
      }

      resources {
        memory=128
      }
    }
    task "processor" {
      driver = "docker"

      volume_mount {
        volume      = "config"
        destination = "/home/mercure/mercure/configuration"
      }
      volume_mount {
        volume      = "data"
        destination = "/home/mercure/mercure-data"
      }
      config {
        image = "yarra/mercure-processor:dev"
        ports = ["dicom"]
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
        image = "mercure/alpine-sshd:dev"
        ports = ["sshd"]
        mount {
          type   = "bind"
          source = "local/ssh"
          target = "/root/.ssh"
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
        image = "yarra/mercure-bookkeeper:dev"
        ports = ["bookkeeper"]
      }

      
      lifecycle {
        hook    = "prestart"
        sidecar = true
      }
      volume_mount {
        volume      = "config"
        destination = "/home/mercure/mercure/configuration"
      }
      volume_mount {
        volume      = "data"
        destination = "/home/mercure/mercure-data"
      }
      env {
        DATABASE_URL = "postgresql://mercure@localhost"
      }
      resources {
        memory=128
      }
    }
  }
}
