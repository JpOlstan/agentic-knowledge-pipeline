resource "aws_cloudwatch_log_group" "lambda" {
  name              = "/aws/lambda/${local.lambda_function_name}"
  retention_in_days = 14
}

resource "aws_cloudwatch_metric_alarm" "dead_letter_not_empty" {
  alarm_name          = "${local.name_prefix}-dlq-not-empty"
  alarm_description   = "At least one request reached the dead-letter queue."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.dead_letter.name }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = 1
  treat_missing_data  = "notBreaching"
}

resource "aws_cloudwatch_metric_alarm" "oldest_request" {
  alarm_name          = "${local.name_prefix}-oldest-request"
  alarm_description   = "The oldest queued request exceeded the configured operating window."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateAgeOfOldestMessage"
  dimensions          = { QueueName = aws_sqs_queue.requests.name }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 5
  comparison_operator = "GreaterThanOrEqualToThreshold"
  threshold           = var.oldest_message_age_alarm_seconds
  treat_missing_data  = "notBreaching"
}
