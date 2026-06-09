# 定义变量
IMAGE_NAME ?= sndraw/bookroom-audio
CONTAINER_NAME ?= bookroom-audio
IMAGE_VERSION ?= $(shell git rev-parse --short HEAD)
REGISTRY_URL ?= docker.io
PLATFORMS ?= linux/amd64,linux/arm64

# 检查命令执行状态的函数
check_error = \
  echo "Error: $1 failed"; \
  exit 1;

.PHONY: build-push-all

build-image:
	@echo "Building web Docker image: $(IMAGE_NAME):$(IMAGE_VERSION)..."
	docker buildx build --platform $(PLATFORMS) -t $(IMAGE_NAME):$(IMAGE_VERSION) ./ || $(call check_error,"build-image")
	@echo "Web Docker image built successfully: $(IMAGE_NAME):$(IMAGE_VERSION)"

tag-image: 
	@echo "Taging web Docker image: $(IMAGE_NAME):$(IMAGE_VERSION)..."
	docker tag $(IMAGE_NAME):$(IMAGE_VERSION) $(REGISTRY_URL)/$(IMAGE_NAME):$(IMAGE_VERSION) || $(call check_error,"tag-image")
	@echo "Web Docker image tag successfully: $(IMAGE_NAME):$(IMAGE_VERSION)"

push-image: 
	@echo "Pushing web Docker image: $(IMAGE_NAME):$(IMAGE_VERSION)..."
	docker push $(REGISTRY_URL)/$(IMAGE_NAME):$(IMAGE_VERSION) || $(call check_error,"push-image")
	@echo "Web Docker image push successfully: $(IMAGE_NAME):$(IMAGE_VERSION)"

run-image:
	# 检查并停止已存在的容器
	docker stop $(CONTAINER_NAME) > /dev/null 2>&1 || true
	docker rm $(CONTAINER_NAME) > /dev/null 2>&1 || true
	@echo "Running web Docker container: $(CONTAINER_NAME)..."
	docker run -d --name $(CONTAINER_NAME) -p 8080:80 $(IMAGE_NAME):$(IMAGE_VERSION) || $(call check_error,"run-image")
	@echo "Web Docker container running successfully: $(CONTAINER_NAME)"

# 使用 docker-compose 启动（推荐，支持缓存挂载）
up:
	@echo "Starting bookroom-audio with docker-compose..."
	docker compose up -d || $(call check_error,"docker-compose-up")
	@echo "bookroom-audio started successfully"

# 使用 docker-compose 停止
down:
	@echo "Stopping bookroom-audio with docker-compose..."
	docker compose down || $(call check_error,"docker-compose-down")
	@echo "bookroom-audio stopped successfully"

# 查看日志
logs:
	docker compose logs -f

# 重建并启动
rebuild:
	@echo "Rebuilding and starting bookroom-audio..."
	docker compose up -d --build || (echo "Warning: docker compose returned non-zero exit code, checking container status..." && docker ps | grep bookroom-audio && echo "Container is running")
	@echo "bookroom-audio rebuilt and started successfully"

# 停止并清理Docker容器和镜像
clean-image:
	@echo "Cleaning web Docker container and image..."
	docker stop $(CONTAINER_NAME) > /dev/null 2>&1 || true
	docker rm $(CONTAINER_NAME) > /dev/null 2>&1 || true
	docker rmi -f $(IMAGE_NAME):$(IMAGE_VERSION) $(REGISTRY_URL)/$(IMAGE_NAME):$(IMAGE_VERSION) > /dev/null 2>&1 || true
	# 清理未被任何容器引用的镜像
	docker image prune -f -a > /dev/null 2>&1 || true
	@echo "Web Docker container and image cleaned successfully."

build-push-all: build-image tag-image push-image