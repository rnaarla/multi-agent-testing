variable "environment" {
  type        = string
  description = "Deployment environment identifier."
}

variable "desired_count" {
  type        = number
  description = "Service replica count."
}

resource "aws_ecs_cluster" "this" {
  name = "multi-agent-${var.environment}"
}

resource "aws_appautoscaling_target" "service" {
  max_capacity       = var.desired_count * 2
  min_capacity       = var.desired_count
  resource_id        = "service/${aws_ecs_cluster.this.name}/backend"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"
}

