client {
    enabled = true
    options { 
        docker.volumes.enabled = true
        docker.cleanup.image = false
    }
    host_volume "mercure-code" {
        path      = "/opt/mercure/app"
        read_only = false
    }
    host_volume "mercure-config" {
        path      = "/opt/mercure/config"
        read_only = false
    }
    host_volume "mercure-data" {
        path      = "/opt/mercure/data"
        read_only = false
    }
    host_volume "mercure-db" {
        path      = "/opt/mercure/db"
        read_only = false
    }
    host_volume "processor-keys" {
        path      = "/opt/mercure/processor-keys"
        read_only = false
    }
}