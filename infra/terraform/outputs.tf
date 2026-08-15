output "lambda_function_name" {
  description = "Lambda function name for operational diagnostics."
  value       = aws_lambda_function.trigger.function_name
}

output "lambda_function_arn" {
  description = "Lambda function ARN."
  value       = aws_lambda_function.trigger.arn
}

output "lambda_function_url" {
  description = "IAM-authenticated Function URL; kept sensitive to avoid casual disclosure."
  value       = aws_lambda_function_url.trigger.function_url
  sensitive   = true
}

output "request_queue_name" {
  description = "SQS request queue name."
  value       = aws_sqs_queue.requests.name
}

output "request_queue_arn" {
  description = "SQS request queue ARN."
  value       = aws_sqs_queue.requests.arn
}

output "request_queue_url" {
  description = "SQS request queue URL; kept sensitive because it contains account context."
  value       = aws_sqs_queue.requests.url
  sensitive   = true
}

output "dead_letter_queue_name" {
  description = "SQS dead-letter queue name."
  value       = aws_sqs_queue.dead_letter.name
}

output "function_url_invoker_policy_json" {
  description = "Least-privilege identity policy template for an authorized Function URL caller."
  value       = data.aws_iam_policy_document.function_url_invoker.json
  sensitive   = true
}
