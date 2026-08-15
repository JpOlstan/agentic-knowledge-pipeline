provider "aws" {
  region = var.aws_region

  default_tags {
    tags = local.common_tags
  }
}

locals {
  name_prefix          = "${var.project_name}-${var.environment}"
  lambda_function_name = "${local.name_prefix}-trigger"
  lambda_package_path  = coalesce(var.lambda_package_path, "${path.module}/../../dist/lambda-trigger.zip")
  common_tags = merge(
    {
      Environment = var.environment
      ManagedBy   = "terraform"
      Project     = var.project_name
    },
    var.tags
  )
}
