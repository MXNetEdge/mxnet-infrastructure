variable "github_credentials" {
  default = {
    GITHUB_USER = ""
    GITHUB_OAUTH_TOKEN = ""
  }
  type = "map"
}

variable "secret_name" {
  default = ""
}
