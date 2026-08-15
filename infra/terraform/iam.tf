data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${local.lambda_function_name}-role"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

data "aws_iam_policy_document" "lambda_execution" {
  statement {
    sid    = "WriteFunctionLogs"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.lambda.arn}:*"]
  }

  statement {
    sid       = "SendOnlyToRequestQueue"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.requests.arn]
  }
}

resource "aws_iam_role_policy" "lambda_execution" {
  name   = "${local.lambda_function_name}-execution"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda_execution.json
}

data "aws_iam_policy_document" "function_url_invoker" {
  statement {
    sid       = "InvokeAuthenticatedFunctionUrl"
    effect    = "Allow"
    actions   = ["lambda:InvokeFunctionUrl"]
    resources = [aws_lambda_function.trigger.arn]

    condition {
      test     = "StringEquals"
      variable = "lambda:FunctionUrlAuthType"
      values   = ["AWS_IAM"]
    }
  }

  statement {
    sid       = "InvokeOnlyThroughFunctionUrl"
    effect    = "Allow"
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.trigger.arn]

    condition {
      test     = "Bool"
      variable = "lambda:InvokedViaFunctionUrl"
      values   = ["true"]
    }
  }
}
