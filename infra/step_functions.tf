data "archive_file" "dq_zip" {
  type        = "zip"
  source_file = "${path.module}/../lambdas/dq_check/lambda_function.py"
  output_path = "${path.module}/build/dq_check.zip"
}

resource "aws_iam_role" "lambda_dq" {
  name = "aml-sentinel-lambda-dq"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "lambda_dq" {
  name = "dq-s3-access"
  role = aws_iam_role.lambda_dq.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${aws_s3_bucket.medallion["bronze"].arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.medallion["bronze"].arn
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:*:*:*"
      }
    ]
  })
}

resource "aws_lambda_function" "dq" {
  function_name    = "aml-sentinel-dq-check"
  role             = aws_iam_role.lambda_dq.arn
  handler          = "lambda_function.lambda_handler"
  runtime          = "python3.12"
  timeout          = 60
  filename         = data.archive_file.dq_zip.output_path
  source_code_hash = data.archive_file.dq_zip.output_base64sha256

  environment {
    variables = {
      BRONZE_BUCKET = aws_s3_bucket.medallion["bronze"].bucket
    }
  }
}

resource "aws_iam_role" "sfn" {
  name = "aml-sentinel-sfn"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "states.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "sfn" {
  name = "sfn-invoke-and-publish"
  role = aws_iam_role.sfn.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = [aws_lambda_function.ingest.arn, aws_lambda_function.dq.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["sns:Publish"]
        Resource = aws_sns_topic.alerts.arn
      }
    ]
  })
}

resource "aws_sfn_state_machine" "pipeline" {
  name     = "aml-sentinel-pipeline"
  role_arn = aws_iam_role.sfn.arn

  definition = jsonencode({
    Comment = "AML Sentinel cloud slice: ingest -> DQ gate -> notify"
    StartAt = "Ingest"
    States = {
      Ingest = {
        Type       = "Task"
        Resource   = aws_lambda_function.ingest.arn
        Retry      = [{ ErrorEquals = ["States.TaskFailed"], IntervalSeconds = 10, MaxAttempts = 2, BackoffRate = 2.0 }]
        Catch      = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.error", Next = "AlertFailure" }]
        Next       = "DQCheck"
      }
      DQCheck = {
        Type       = "Task"
        Resource   = aws_lambda_function.dq.arn
        Retry      = [{ ErrorEquals = ["States.TaskFailed"], IntervalSeconds = 10, MaxAttempts = 1, BackoffRate = 2.0 }]
        Catch      = [{ ErrorEquals = ["States.ALL"], ResultPath = "$.error", Next = "AlertFailure" }]
        Next       = "AlertSuccess"
      }
      AlertSuccess = {
        Type     = "Task"
        Resource = "arn:aws:states:::sns:publish"
        Parameters = {
          TopicArn = aws_sns_topic.alerts.arn
          Subject  = "AML Sentinel pipeline: SUCCESS"
          "Message.$" = "States.JsonToString($)"
        }
        End = true
      }
      AlertFailure = {
        Type     = "Task"
        Resource = "arn:aws:states:::sns:publish"
        Parameters = {
          TopicArn = aws_sns_topic.alerts.arn
          Subject  = "AML Sentinel pipeline: FAILED"
          "Message.$" = "States.JsonToString($)"
        }
        Next = "FailState"
      }
      FailState = {
        Type = "Fail"
      }
    }
  })
}

output "state_machine_arn" {
  value = aws_sfn_state_machine.pipeline.arn
}
