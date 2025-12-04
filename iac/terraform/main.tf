terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

variable "region" {
  type        = string
  description = "AWS region used for deployments."
  default     = "us-east-1"
}

module "backend_canary" {
  source = "./modules/backend"

  environment = "canary"
  desired_count = 1
}

module "backend_prod" {
  source = "./modules/backend"

  environment = "prod"
  desired_count = 3
}

