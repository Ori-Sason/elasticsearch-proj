# User background

## Summary & Technical Profile

* **Name:** Ori Sason (CPA, Full-Stack & DevOps Software Engineer)
* **Background:** Transitioned from a rigorous analytical background as a Certified Public Accountant (CPA) into Full-Stack Software Engineering and Cloud/DevOps Systems Engineering.
* **Workstation & Dev Environment:** Windows 11 host (AMD Ryzen 7 5800H), WSL2, VirtualBox, Hyper-V, and Multipass managing custom `cloud-init` Ubuntu VMs provisioned with Docker, Python `uv`, TypeScript, and orchestrated via VS Code Remote SSH.
* **Primary Tech Stack:**
  * **Languages & Web:** Python, Node.js, TypeScript, React, Flask, Express
  * **Data Stores:** PostgreSQL, MySQL, SQLite, MongoDB
  * **Containers & Orchestration:** Docker, Kubernetes, K3s, Helm, ArgoCD (GitOps)
  * **CI/CD & Automation:** GitHub Actions, Jenkins, Ansible
  * **Infrastructure as Code & Cloud:** Terraform, AWS (EC2, Auto Scaling Groups, VPC, Subnets, Route Tables, IGW/NAT, Security Groups, NACLs, ALB, RDS, Secrets Manager, SSM Parameter Store, Lambda, SQS)
  * **Observability:** Prometheus, Grafana, Alertmanager

---

## Formal Training & Certifications

### Full-Stack Engineering Bootcamp (Coding Academy — Completed)
* Completed intensive curriculum covering JS/TS fundamentals, HTTP/HTTPS protocols, responsive HTML/CSS (Grid/Flexbox), React, Redux state management, Node.js/Express REST APIs, WebSockets, MySQL, MongoDB, MVC architecture, Vite build tooling, and PWA mechanics.

### DevOps Experts Academy (Completed 15-Session Industrial Program)
1. **DevOps Foundations & Linux Admin:** Linux CLI tools, permission models, SSH configurations, and network troubleshooting utilities.
2. **Docker Containerization:** Multi-stage builds, Dockerfile optimization, container networking, bridge drivers, volume persistence.
3. **Kubernetes Core:** Cluster architecture, Pods, ReplicaSets, Deployments, ClusterIP/NodePort/LoadBalancer Services.
4. **Kubernetes Advanced:** Persistent Volumes (PV/PVC), ConfigMaps, Secrets, Horizontal Pod Autoscaler (HPA), Jobs, CronJobs.
5. **Package Management with Helm:** Custom chart construction, dependency management, Artifact Hub, plugins, CI/CD integration.
6. **Version Control & Git Workflows:** Low-level Git mechanics, branching models, interactive rebase, cherry-picking, detached HEAD resolution, conflict strategies.
7. **CI/CD Automation:** Multi-job pipelines in GitHub Actions & Jenkins, triggers, matrix builds, artifacts, reusable workflows, secrets integration.
8. **GitOps:** Continuous delivery principles, ArgoCD auto-sync, self-healing, rollback mechanics, Helm & Kustomize integration.
9. **Monitoring & Observability:** Prometheus metrics scraping/storage, Alertmanager routing, custom Grafana dashboards, log aggregation.
10. **AWS Cloud Infrastructure:** EC2 lifecycle, IAM roles/policies, Elastic IPs, Security Groups, ALB load balancing, AWS CLI workflows.
11. **Infrastructure as Code (Terraform):** Declarative HCL, provider configs, custom module architecture, state management & remote backends.
12. **AWS Networking & Storage:** Custom VPC design (CIDR block allocation, public/private subnets, route tables, Internet/NAT Gateways), NACLs, AWS RDS (PostgreSQL/MySQL).
13. **AWS Secrets & Serverless:** AWS Lambda event-driven compute, AWS Secrets Manager, SQS queuing, K3s orchestration, LocalStack emulation.
14. **Configuration Management (Ansible):** YAML Playbooks, ad-hoc execution, inventory host group management, custom Ansible modules.
15. **E2E Enterprise Pipeline & Architecture:** Multi-phase production architecture incorporating Python Flask, PostgreSQL, Docker Hub, Kubernetes, Helm, GitHub Actions, Jenkins, Prometheus, Grafana, AWS K3s cluster via Terraform, AWS SSM Parameter Store, and External Secrets Operator.

---

## Verified Knowledge & Coursework

| Status | Course Title & Provider | Focus Area |
| :--- | :--- | :--- |
| **100% Completed** | *Claude Code - The Practical Guide* (Academind) | AI-Assisted CLI Workflows & Automation |
| **100% Completed** | *Docker & Kubernetes: The Practical Guide* (Academind) | Containerization & Orchestration |
| **100% Completed** | *GitHub Actions - The Complete Guide* (Academind) | CI/CD Pipeline Automation |
| **100% Completed** | *Cypress End-to-End Testing* (Academind) | E2E Testing Mechanics |
| **100% Completed** | *JavaScript Unit Testing - The Practical Guide* (Academind) | Unit & Integration Testing Strategies |
| **100% Completed** | *Practical SQL With Python In 3 Days* (Andy Bek) | Relational Database Manipulation |
| **100% Completed** | *The Ultimate JSON With Python Course + JSONSchema & JSONPath* (Andy Bek) | Data Serialization, Schemas & Parsing |
| **100% Completed** | *Python Object Oriented Programming (OOP)* (Andy Bek) | Advanced Object-Oriented Architecture |
| **100% Completed** | *Building GraphQL APIs with Python* (Andy Bek) | Schema Design & Resolver Mechanics |
| **100% Completed** | *Intermediate Python: Master Decorators From Scratch* (Andy Bek) | Metaprogramming & Wrapper Patterns |
| **100% Completed** | *Clean Code* (Academind) | Software Refactoring & Maintainability |
| **100% Completed** | *Python - The Practical Guide* (Academind) | Core Python System Architecture |
| **100% Completed** | *Networking* (pracnet.net) | Computer Networking Fundamentals, OSI/TCP-IP Models, Subnetting, Routing & Switching |
| **100% Completed** | *Network Address Translation* (pracnet.net) | Static/Dynamic NAT, PAT, Port Forwarding & Packet Header Translation Mechanics |
| **98% Completed** | *Fundamentals of Backend Engineering* (Hussein Nasser) | Network Protocols, OS Systems & Backend Architecture |
| **85–95% Completed** | *Master the Coding Interview: DS+Algo & FAANG* | Algorithmic Complexity, Data Structures |
| **82% Completed** | *Decoding DevOps – Basics to Advanced Projects with AI* (Imran Teli) | End-to-End DevOps Integration |
| **79% Completed** | *Understanding TypeScript* (Academind) | Type Systems, Generics & Compiler Mechanics |
| **57% Completed** | *Fundamentals of Database Engineering* (Hussein Nasser) | Database Internals, Storage Engines, Indexing, B-Trees |
| **52% Completed** | *AI Agents & Workflows - The Practical Guide* | Autonomous Agent Pipelines & Orchestration |
| **Active Reference** | *Fundamentals of Network Engineering* (Hussein Nasser) | OSI Model, Sockets, Transport Layer Protocols |
| **Active Reference** | *Fundamentals of Operating Systems* (Hussein Nasser) | Kernel Mechanics, Memory, System Calls, Threading |

---

## Systems & Infrastructure Projects

* **Low-Level Socket Server (Node.js):**
  * Implemented a promise-based TCP socket server from scratch in raw Node.js, implementing low-level `TCPConn`, `soRead`, `soWrite`, and `soAccept` wrappers based on James Smith's engineering patterns.
* **OS & Protocol Deep Dives:**
  * In-depth study of OSI model mechanics, socket lifecycles, connection handshakes, database storage engine internals, indexing strategies, and execution engines (via *pracnet.net* and Hussein Nasser's backend architecture studies).
* **Enterprise DevOps Cloud Architecture (`Ori-Sason/devops-experts-final-project`):**
  * Provisioned a production-ready AWS K3s Kubernetes cluster via Terraform across multi-AZ VPCs with Auto Scaling Groups.
  * Secured infrastructure state and configuration by synchronizing secrets from AWS SSM Parameter Store into K3s using External Secrets Operator.
  * Continuous Delivery pipeline managed through Jenkins and GitHub Actions pushing images to Docker Hub, continuous deployment managed via Helm and ArgoCD GitOps, fully monitored with Prometheus metrics and custom Grafana dashboards.
* **Custom Virtualized Dev Environment:**
  * Provisioned reproducible local environment using Multipass `cloud-init` configurations on WSL2/Windows 11, integrating Python `uv` package management, Docker engine, and VS Code Remote SSH setups.

---

## How to Apply (Calibrating AI Output)

### Topics to NEVER Over-Explain or Detail Intro Concepts For:
* **Basic Web APIs:** Do not explain HTTP verbs, standard REST conventions, basic JSON payload structures, or basic GraphQL schema syntax.
* **Containerization & Orchestration:** Do not explain what Docker containers, images, Dockerfiles, Kubernetes Pods, Deployments, Services, or Helm Charts are. Skip basic syntax for manifests.
* **Git & Version Control:** Skip explanations of standard Git flows, `git rebase`, interactive rebase, cherry-picking, merge strategies, or detached HEAD states.
* **Linux Fundamentals:** Do not explain basic Linux CLI usage, permission models, or SSH configuration/key setup.
* **Infrastructure as Code & Configuration:** Skip explanations of basic Terraform resource syntax, HCL blocks, state files, or Ansible playbook structure.
* **Networking Fundamentals:** Do not explain the OSI model, TCP/IP basics, subnetting, routing/switching, or NAT/PAT/port-forwarding mechanics.
* **Cloud Architecture & Networking:** Do not explain basic AWS concepts (EC2, VPC CIDR blocks, Public/Private subnets, IGW/NAT, Security Groups, NACLs, S3, RDS).
* **Language Specifics:** Skip explanations of basic/intermediate Python syntax, OOP concepts, decorator wrapper syntax, JavaScript promises/async-await, or TypeScript typing basics.

### Execution Directives for AI Agents:
1. **Assume Advanced Technical Depth:** Always skip high-level overviews and jump straight into mechanism-level mechanics, low-level execution paths, and architecture trade-offs.
2. **Prioritize System Internals:** When discussing databases, operating systems, networking, or infrastructure, focus on memory management, system calls, storage engine internals, socket options, packet traversal, and state lifecycle mechanics.
3. **No Conversational Fluff:** Omit introductory setups (e.g., *"Here is a breakdown of..."*). Present technical information immediately using structured Markdown, step-by-step logic, code blocks, or comparison tables.
