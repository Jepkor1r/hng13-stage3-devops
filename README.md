# 🌐 Blue–Green Deployment with Nginx and Docker

## 🧩 Overview

- This project demonstrates a **Blue-Green Deployment** strategy using **Docker**, **Nginx**, and a simple **Node.js** web application.

- The goal is to achieve **zero downtime deployment** — where a new version of an app (Green) can take over seamlessly if the current one (Blue) fails or is being updated.

- It works by running two identical environments — one active (Blue) and one idle (Green).

----

## 🧠 What You’ll Learn:
- How to containerize apps using **Docker**
- How to manage multiple environments (Blue & Green)
- How **Nginx** works as a reverse proxy and load balancer
- How to perform **failover testing**
- How to simulate app failure using a **chaos endpoint**
- The real-world idea behind **zero downtime deployment**

----

## 🏗️ Project Structure

```bash
hng13-stage2-devops/
│
├── nginx/                     # Nginx as reverse proxy and load balancer
│   ├── docker-entrypoint.sh
│   └── nginx.conf.base
│
├── nginx.conf.template         # Nginx configuration for Blue–Green routing
│
├── ci/
│   └── test_failover.sh        # Automated failover test script
│
├── .env                        # Environment variables
│
├── docker-compose.yml          # Defines and connects all services
│
└── README.md                   # Project documentation
```
----

## 🐳 How It Works (Simple Story Version)

✨Imagine two identical kitchens:

- Blue Kitchen (app_blue) → The current live app

- Green Kitchen (app_green) → The standby version

✨Nginx is the restaurant front desk that takes orders from customers and decides which kitchen to send them to.

✨Normally, Nginx sends everything to Blue.

✨If Blue’s oven breaks (we simulate that using a chaos endpoint), Nginx quickly switches to Green, keeping everything running smoothly.

### 🧱 Step 1: Build the Docker Image

The Dockerfile defines how to build the web app container. 

It:
- Uses Node.js as a base image.
- Copies the app source code.
- Installs dependencies.
- Runs the app on port 8080.

To build:

```bash 
docker build -t myapp:latest .
```

### 🚀 Step 2: Run All Services with Docker Compose

docker-compose.yml sets up three containers:

- app_blue → Runs on port 8081
- app_green → Runs on port 8082
- nginx → Serves as a reverse proxy on port 8080

Start everything:

```bash
docker-compose up -d
```

Check running containers:

```bash
docker ps
```

You should see:

```bash
app_blue
app_green
nginx
```

### 🌍 Step 3: Test the Running Apps

Try visiting or curling the following URLs:

```bash
curl http://localhost:8081/version   # Blue app directly
curl http://localhost:8082/version   # Green app directly
curl http://localhost:8080/version   # Through Nginx proxy
```

You’ll see headers like:

```bash
X-App-Pool: blue

or

X-App-Pool: green
```

### 💥 Step 4: Simulate a Failure

We can intentionally “break” the Blue app using the chaos endpoint:

```bash
curl -X POST "http://localhost:8081/chaos/start?mode=error"
```

Now, the Blue app will start returning 500 errors.

Nginx detects this and automatically reroutes traffic to the Green app — no downtime!

You can confirm by running:

```bash
curl -i http://localhost:8080/version | grep X-App-Pool
```

You should now see:

```bash
X-App-Pool: green
```

### 🔧 Step 5: Stop the Chaos (Return to Normal)

To stop Blue’s error mode:

```bash
curl -X POST http://localhost:8081/chaos/stop
```

Now Nginx can safely send traffic back to Blue again.

### 🧪 Step 6: Run the Automated Test

The ci/test_failover.sh script automatically:
- Checks that Blue is serving traffic.
- Triggers chaos mode on Blue.
- Sends 50 requests to Nginx.
- Verifies that at least 95% of them are served by Green.

Run the test:

``` bash 
./ci/test_failover.sh
```

## ✅ Expected Output:

PASS: Failover successful. 100% of requests served by Green with 0 non-200s.

## 🔁 Summary of Traffic Flow
| Situation | Nginx Routes Traffic To | Why |
|------------|--------------------------|-----|
| **Normal** | Blue (8081) | Blue is healthy |
| **Blue Fails** | Green (8082) | Nginx detects Blue’s errors |
| **Blue Fixed** | Blue (8081) | You can switch back manually |

## 🧰 Commands Reference
- Start all containers ---> docker-compose up -d
- Stop all containers	---> docker-compose down
- View logs ---> docker-compose logs -f
- Test Nginx routing --->	curl -i http://localhost:8080/version
- Trigger chaos --->	curl -X POST http://localhost:8081/chaos/start?mode=error
- Stop chaos --->	curl -X POST http://localhost:8081/chaos/stop
- Run automated test --->	./ci/test_failover.sh

## 🧠 Concepts You’ve Practiced
- Docker Image: A packaged version of your app with all dependencies
- Docker Container: A running instance of your image
- Reverse Proxy: Nginx forwards traffic to Blue or Green
- Failover: Automatic switch to a healthy service when one fails
- Zero Downtime: Users never see an outage, even during updates
- Chaos Testing: Simulating failures to check system resilience

## 💡 Key Takeaways
Both Blue and Green apps run from the same code, but on different ports.

Nginx intelligently decides which one should receive