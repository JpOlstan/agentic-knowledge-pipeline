resource "aws_lambda_function" "trigger" {
  filename         = local.lambda_package_path
  function_name    = local.lambda_function_name
  role             = aws_iam_role.lambda.arn
  handler          = "knowledge_agents.entrypoints.lambda_handler.lambda_handler"
  runtime          = "python3.12"
  architectures    = [var.lambda_architecture]
  memory_size      = 128
  timeout          = 10
  source_code_hash = filebase64sha256(local.lambda_package_path)

  environment {
    variables = {
      KA_SQS_QUEUE_URL = aws_sqs_queue.requests.url
    }
  }

  depends_on = [
    aws_cloudwatch_log_group.lambda,
    aws_iam_role_policy.lambda_execution,
  ]
}

resource "aws_lambda_function_url" "trigger" {
  function_name      = aws_lambda_function.trigger.function_name
  authorization_type = "AWS_IAM"
  invoke_mode        = "BUFFERED"
}
