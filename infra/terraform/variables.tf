variable "aws_region" {
  description = "AWS region for the trigger resources."
  type        = string
  default     = "us-east-1"

  validation {
    condition     = can(regex("^[a-z]{2}(-gov)?-[a-z]+-[0-9]+$", var.aws_region))
    error_message = "aws_region must be a valid AWS region name."
  }
}

variable "project_name" {
  description = "Stable project prefix used in resource names and tags."
  type        = string
  default     = "knowledge-agents"

  validation {
    condition     = can(regex("^[a-z0-9][a-z0-9-]{1,30}[a-z0-9]$", var.project_name))
    error_message = "project_name must contain 3-32 lowercase letters, digits, or hyphens."
  }
}

variable "environment" {
  description = "Deployment environment suffix."
  type        = string
  default     = "dev"

  validation {
    condition     = contains(["dev", "test", "prod"], var.environment)
    error_message = "environment must be dev, test, or prod."
  }
}

variable "lambda_architecture" {
  description = "Architecture used by the reproducible Lambda package."
  type        = string
  default     = "x86_64"

  validation {
    condition     = contains(["x86_64", "arm64"], var.lambda_architecture)
    error_message = "lambda_architecture must be x86_64 or arm64."
  }
}

variable "lambda_package_path" {
  description = "Optional local path to the Lambda ZIP; defaults to dist/lambda-trigger.zip."
  type        = string
  default     = null
  nullable    = true
}

variable "oldest_message_age_alarm_seconds" {
  description = "Maximum acceptable age of the oldest message before alarming."
  type        = number
  default     = 3600

  validation {
    condition     = var.oldest_message_age_alarm_seconds >= 180
    error_message = "oldest_message_age_alarm_seconds must be at least the visibility timeout."
  }
}

variable "tags" {
  description = "Additional non-sensitive tags."
  type        = map(string)
  default     = {}
}
