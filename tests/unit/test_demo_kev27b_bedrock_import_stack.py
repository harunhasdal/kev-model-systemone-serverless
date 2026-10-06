import aws_cdk as core
import aws_cdk.assertions as assertions

from demo_kev27b_bedrock_import.demo_kev27b_bedrock_import_stack import DemoKev27BBedrockImportStack

# example tests. To run these tests, uncomment this file along with the example
# resource in demo_kev27b_bedrock_import/demo_kev27b_bedrock_import_stack.py
def test_sqs_queue_created():
    app = core.App()
    stack = DemoKev27BBedrockImportStack(app, "demo-kev27b-bedrock-import")
    template = assertions.Template.from_stack(stack)

#     template.has_resource_properties("AWS::SQS::Queue", {
#         "VisibilityTimeout": 300
#     })
