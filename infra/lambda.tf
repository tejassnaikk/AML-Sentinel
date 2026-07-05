data "archive_file" "ingest_zip" {
  type        = "zip"
  source_file = "${path.module}/../lambdas/ingest_loader/lambda_function.py"
  output_path = "${path.module}/build/ingest_loader.zip"
}

resource "aws_iam_role" "lambda_ingest" {
  name = "aml-sentinel-lambda-ingest"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy" "lambda_ingest" {
  name = "ingest-s3-access"
  role = aws_iam_role.lambda_ingest.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["s3:GetObject"]
        Resource = "${aws_s3_bucket.medallion["scripts"].arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = [
          aws_s3_bucket.medallion["scripts"].arn,
          aws_s3_bucket.medallion["bronze"].arn
        ]
      },
      {
        Effect   = "Allow"
        Action   = ["s3:PutObject", "s3:GetObject"]
        Resource = "${aws_s3_bucket.medallion["bronze"].arn}/*"
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "arn:aws:logs:*:*:*"
      }
    ]
  })
}

resource "aws_lambda_function" "ingest" {
  function_name    = "aml-sentinel-ingest"
  role             = aws_iam_role.lambda_ingest.arn
  handler          = "lambda_function.lambda_handler"
  runtime          = "python3.12"
  timeout          = 120
  filename         = data.archive_file.ingest_zip.output_path
  source_code_hash = data.archive_file.ingest_zip.output_base64sha256

  environment {
    variables = {
      SOURCE_BUCKET = aws_s3_bucket.medallion["scripts"].bucket
      SOURCE_KEY    = "source/HI-Small_Trans.csv"
      BRONZE_BUCKET = aws_s3_bucket.medallion["bronze"].bucket
    }
  }
}

output "ingest_lambda_arn" {
  value = aws_lambda_function.ingest.arn
}
