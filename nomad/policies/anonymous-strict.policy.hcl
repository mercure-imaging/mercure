namespace "*" {
   policy = "read"
   capabilities = ["read-logs", "read-job", "list-jobs", "submit-job", "dispatch-job"]
}

agent {
   policy = "read"
}

operator {
   policy = "read"
}

quota {
   policy = "read"
}

node {
   policy = "read"
}

host_volume "*" {
   policy = "write"
}
