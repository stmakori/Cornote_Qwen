# Cloud Forge Series - Week 1: EC2 Fundamentals
### AWS Student Builder Group | Egerton University

Your complete reference guide for Week 1 - understanding Amazon EC2, launching your first instance, and deploying a live web server.

**Presented by:** Stephanie Makori
**Session Date:** 11th June 2026
**Version:** 1.0
**Duration to complete lab:** 30–45 minutes
**Difficulty:** Beginner (no prior cloud experience required)

---

## Table of Contents

1. [What You Will Accomplish](#what-you-will-accomplish)
2. [Prerequisites](#prerequisites)
3. [What is EC2?](#what-is-ec2)
4. [Key Concepts](#key-concepts)
   - [Instance Families](#instance-families)
   - [Pricing Models](#pricing-models)
   - [Amazon Machine Images (AMI)](#amazon-machine-images-ami)
   - [Key Pairs](#key-pairs)
   - [Security Groups](#security-groups)
   - [User Data](#user-data)
5. [Hands-On Lab: Launch Your First EC2 Instance](#hands-on-lab-launch-your-first-ec2-instance)
   - [Step 1: Open EC2 Console](#step-1-open-ec2-console)
   - [Step 2: Configure Your Instance](#step-2-configure-your-instance)
   - [Step 3: Set Up Key Pair](#step-3-set-up-key-pair)
   - [Step 4: Configure Security Group](#step-4-configure-security-group)
   - [Step 5: Add User Data Script](#step-5-add-user-data-script)
   - [Step 6: Launch and Verify](#step-6-launch-and-verify)
   - [Step 7: Terminate Your Instance](#step-7-terminate-your-instance)
6. [Common Problems & Solutions](#common-problems--solutions)
7. [Quick Reference Card](#quick-reference-card)
8. [Need Help?](#need-help)

---

## What You Will Accomplish

By the end of this session and lab, you will have:

| Item | Why It Matters |
|------|----------------|
| ✅ Understanding of EC2 core concepts | Foundation for every AWS workload you will ever build |
| ✅ Knowledge of instance families & pricing | Make cost-smart choices in real projects |
| ✅ Configured a Security Group | Control traffic to your server like a professional |
| ✅ Launched a live EC2 instance | First real cloud server - yours, in minutes |
| ✅ Deployed an Apache web server via User Data | Automation from day one - no manual SSH needed |
| ✅ Served a webpage from the cloud | Hit your instance's public IP and see your page live |
| ✅ Safely terminated your instance | Good hygiene - never leave free-tier resources running |

---

## Prerequisites

Before starting the lab, confirm you have everything below. If you completed the Sprint Pre-Games setup guide, you are ready.

| Requirement | Details |
|-------------|---------|
| AWS Account | Active and fully verified (from Pre-Games setup) |
| IAM Admin User | You should log in as `[yourname]-admin`, never as root |
| Budget Alert | $5 alert active - protects against accidental charges |
| Device | Laptop (Windows, Mac, or Linux) with a modern browser |
| Internet | Stable connection (campus Wi-Fi or mobile hotspot) |

> **Important:** Always sign in using your **IAM user** URL, not the root account. Your IAM sign-in URL is in the `.csv` file you downloaded during Pre-Games setup.

---

## What is EC2?

**Amazon Elastic Compute Cloud (EC2)** is a web service that provides secure, resizable compute capacity in the cloud. It allows you to launch virtual servers (called **instances**) in minutes, with no upfront hardware costs.

You have complete control over your instances - including root access, choice of operating system (Linux or Windows), and what software is installed.

### Why EC2 Matters

| Property | What It Means for You |
|----------|----------------------|
| **Elastic** | Scale up or down within minutes, even automatically |
| **Reliable** | 99.99% availability SLA across multiple Availability Zones |
| **Secure** | Integrates with IAM, VPC, and Security Groups |
| **Cost Effective** | Free Tier eligible - 750 hours/month of `t2.micro` |
| **Flexible** | Hundreds of instance types optimized for different workloads |

---

## Key Concepts

### Instance Families

EC2 offers **100+ instance types** grouped into families optimised for different workloads. Choosing the right family balances performance, cost, and features.

| Family | Optimised For | Examples | Use Case |
|--------|--------------|---------|---------|
| **General Purpose (T)** | Balanced compute/memory, burstable CPU | `t2.micro`, `t3.micro`, `t4g.micro` | Web servers, dev environments, small databases |
| **Compute Optimised (C)** | High CPU-to-memory ratio | `c6g.large` | Batch processing, gaming servers, ad serving |
| **Memory Optimised (R/X)** | Large RAM | `r6g.large` | In-memory databases, real-time analytics |
| **Storage Optimised (I/D)** | High sequential read/write | `i3.large` | Data warehouses, log processing |
| **Accelerated Computing (P/G/Inf)** | GPUs | `g4dn.xlarge` | ML training, graphics rendering |

> **Free Tier Eligible:** `t2.micro` or `t3.micro` - **750 hours/month**. This is what you will use in the lab today.

---

### Pricing Models

You do not have to pay the same way for every workload. AWS offers several pricing models so you only pay for what you need.

| Model | How It Works | Savings | Best For |
|-------|-------------|---------|---------|
| **On-Demand** | Pay by the hour/second, no commitment | Baseline | Development, unpredictable workloads |
| **Savings Plans** | Commit to a usage level for 1–3 years | Up to **72%** | Steady, predictable workloads |
| **Spot Instances** | Bid on spare AWS capacity | Up to **90%** | Fault-tolerant, interruptible jobs |
| **Free Tier** | 750 hours/month of `t2.micro` for 12 months | 100% | Learning and this entire sprint |

> For this sprint, you will always stay on **Free Tier**. Your $5 budget alert will warn you if anything goes wrong.

---

### Amazon Machine Images (AMI)

An **AMI (Amazon Machine Image)** is a pre-packaged snapshot of an operating system. Think of it as the **blueprint for your server** - every EC2 instance is born from an AMI.

- For today's lab you will select **Amazon Linux 2023** (free tier eligible).
- AMIs can also be custom - you can snapshot your configured server and relaunch it later.

---

### Key Pairs

AWS uses a **key pair** to verify your identity when connecting to an instance via SSH.

| Part | Where It Lives | Your Responsibility |
|------|---------------|-------------------|
| **Public key** | Stored on AWS | Automatically placed on your instance |
| **Private key (.pem file)** | Downloaded to your laptop once | **Never share this. Never lose this.** |

> If you lose your `.pem` file, you lose SSH access to that instance permanently. There is no recovery. Guard it like a password.

---

### Security Groups

A **Security Group** is a virtual firewall around your EC2 instance. You define rules that control which traffic is allowed in - AWS enforces them at the network layer before traffic ever reaches your server.

**Default behaviour:** ALL inbound traffic is **BLOCKED**. Your instance will be running but completely unreachable until you explicitly open a port.

| Direction | Default | Controlled By |
|-----------|---------|--------------|
| **Inbound** | All blocked | Rules you add |
| **Outbound** | All allowed | Rules you add (we leave this default) |

#### Lab Required Inbound Rule

| Type | Protocol | Port | Source | Purpose |
|------|----------|------|--------|---------|
| SSH | TCP | 22 | My IP | Connect to your instance from your laptop |
| HTTP | TCP | 80 | 0.0.0.0/0 (Anywhere) | Allow browsers to load your web page |

> Without the **HTTP port 80 rule**, your browser will time out - even if Apache is running perfectly inside the instance.

---

### User Data

Instead of typing commands manually after launch, EC2 lets you supply a **script that runs automatically at first boot**. This is called **User Data** and is your first taste of Infrastructure as Code.

Key facts:
- Runs **once**, automatically, during the launch sequence - no SSH required.
- Runs as **root** - no `sudo` needed inside the script.
- Paste it into: **Advanced Details → User Data** in the EC2 launch wizard.

#### Lab User Data Script

```bash
#!/bin/bash
yum update -y
yum install -y httpd
systemctl start httpd
systemctl enable httpd
MSG='<h1>Hello from'
MSG="$MSG $(hostname -f)</h1>"
echo "$MSG" > /var/www/html/index.html
```

> After launch, wait ~60 seconds, then open your instance's public IP in a browser. You will see your web page live.

---

## Hands-On Lab: Launch Your First EC2 Instance

### Step 1: Open EC2 Console

1. Sign in at your IAM user URL (from your Pre-Games `.csv` file).
2. In the AWS search bar, type **EC2** and click it.
3. Click **"Launch instance"**.

---

### Step 2: Configure Your Instance

Fill in the launch wizard fields as follows:

| Field | Value |
|-------|-------|
| Name | `week1-webserver` |
| AMI | Amazon Linux 2023 (Free tier eligible) |
| Instance type | `t2.micro` (Free tier eligible) |
| Key pair | See Step 3 below |

---

### Step 3: Set Up Key Pair

1. Click **"Create new key pair"**.
2. Fill in the details:

   | Field | Value |
   |-------|-------|
   | Key pair name | `week1-key` |
   | Key pair type | RSA |
   | Private key format | `.pem` (Mac/Linux) or `.ppk` (Windows with PuTTY) |

3. Click **"Create key pair"** - your browser will download the file automatically.
4. **Move this file somewhere safe on your laptop. Do not delete it.**

---

### Step 4: Configure Security Group

1. Under **"Network settings"**, click **"Edit"**.
2. Create a new security group:

   | Field | Value |
   |-------|-------|
   | Security group name | `week1-sg` |
   | Description | `Week 1 lab - allow SSH and HTTP` |

3. You will see a default SSH rule already present. Add a second rule:
   - Click **"Add security group rule"**
   - Type: **HTTP**
   - Protocol: TCP
   - Port range: **80**
   - Source: **0.0.0.0/0** (Anywhere)

---

### Step 5: Add User Data Script

1. Scroll down to **"Advanced details"**.
2. Scroll to the very bottom to find the **"User data"** text box.
3. Paste the script below exactly as written:

```bash
#!/bin/bash
yum update -y
yum install -y httpd
systemctl start httpd
systemctl enable httpd
MSG='<h1>Hello from'
MSG="$MSG $(hostname -f)</h1>"
echo "$MSG" > /var/www/html/index.html
```

---

### Step 6: Launch and Verify

1. In the summary panel on the right, confirm:
   - Instance type: `t2.micro`
   - Number of instances: `1`
2. Click **"Launch instance"**.
3. Click **"View all instances"** to return to the EC2 dashboard.
4. Wait until your instance shows **"Running"** and the status checks show **"2/2 checks passed"** (takes 1–3 minutes).
5. Click on your instance to see its details.
6. Copy the **Public IPv4 address**.
7. Open a new browser tab and go to: `http://YOUR_PUBLIC_IP`

   You should see:
   ```
   Hello from ip-172-xx-xx-xx.ec2.internal
   ```

✅ **Your web server is live on the internet.**

---

### Step 7: Terminate Your Instance

Once you have confirmed your web page loads, **terminate the instance** to protect your free tier hours.

1. On the EC2 Instances page, check the box next to `week1-webserver`.
2. Click **"Instance state"** → **"Terminate instance"**.
3. Click **"Terminate"** to confirm.

> **Why terminate?** A running instance counts against your 750 free hours/month. Always terminate lab instances when you are done.

✅ **Lab complete. Well done!**

---

## Common Problems & Solutions

### Problem 1: "My browser times out when I visit the public IP"

**Why this happens:** The Security Group is missing the HTTP port 80 inbound rule, or the User Data script did not run correctly.

**Solutions:**
- Go to EC2 → Instances → Click your instance → **Security** tab → Check the inbound rules. You should see a rule for port 80.
- If port 80 is missing: Go to **Security Groups** → Edit inbound rules → Add HTTP rule → Save.
- If port 80 exists: The User Data script may have had a typo. Terminate this instance and relaunch with the correct script.

---

### Problem 2: "My instance is stuck in 'Pending' for more than 5 minutes"

**Why this happens:** Rarely, AWS has capacity issues in a region or AZ.

**Solutions:**
- Wait a few more minutes - it usually resolves.
- If still pending after 10 minutes: Terminate it and launch a new one. Choose a different Availability Zone if given the option.

---

### Problem 3: "I can't find the User Data field"

**Why this happens:** It is hidden inside Advanced Details, which is collapsed by default.

**Solution:**
- In the EC2 launch wizard, scroll down to **"Advanced details"** and click the arrow to expand it.
- Then scroll to the very bottom of that section - **User data** is the last field.

---

### Problem 4: "I lost my .pem key file"

**Why this happens:** The file was not saved after download, or it was accidentally deleted.

**Solutions:**
- Unfortunately, there is no way to recover a lost private key from AWS.
- Terminate the instance and create a new one with a new key pair.
- This time, save the `.pem` file in a dedicated folder (e.g., `~/aws-keys/`) and back it up.

---

### Problem 5: "The page shows the Apache test page, not my Hello message"

**Why this happens:** The User Data script ran but the `echo` command had a problem, so Apache shows its default page.

**Solution:**
- SSH into the instance and check the file: `cat /var/www/html/index.html`
- If the file is empty or missing, run the echo command manually:
  ```bash
  echo "<h1>Hello from $(hostname -f)</h1>" > /var/www/html/index.html
  ```
- Refresh your browser.

---

### Problem 6: "I'm worried I've been charged"

**Why this happens:** `t2.micro` is free - but if you accidentally launched a different instance type, or left it running for many hours, charges are possible.

**Solutions:**
- First, check your running instances: EC2 → Instances → Make sure nothing unexpected is running.
- Check your budget: Billing Dashboard → Budgets → Confirm your $5 alert is active.
- If you see unexpected charges: Go to AWS Support → Create case → Account and Billing. Students often receive a one-time courtesy waiver.

---

## Quick Reference Card

### Lab Instance Details (Fill This In)

| Item | Your Value |
|------|-----------|
| Instance ID | `i-0...` |
| Public IPv4 address | `x.x.x.x` |
| Key pair name | `week1-key` |
| Security group name | `week1-sg` |
| AMI used | Amazon Linux 2023 |
| Instance type | `t2.micro` |
| Instance terminated? | ✅ Yes / ❌ No |

---

### Important URLs

| URL | Purpose |
|-----|---------|
| `https://console.aws.amazon.com` | AWS Management Console |
| `https://your-account-id.signin.aws.amazon.com/console` | Your IAM user login |
| `http://YOUR_PUBLIC_IP` | Your live web server (replace with actual IP) |
| `https://aws.amazon.com/free` | Free tier details & limits |

---

### Emergency: Stop Everything Fast

If you think you have left resources running accidentally:

1. Go to **EC2 → Instances** → Select all running instances → **Terminate**
2. Go to **Billing Dashboard → Budgets** → Confirm your $5 alert is still active
3. Go to **EC2 → Elastic IPs** → Release any unattached IPs (these cost money)

---

## Need Help?

### Self-Help Resources

| Resource | Link |
|----------|------|
| EC2 Getting Started | https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/EC2_GetStarted.html |
| EC2 Instance Types | https://aws.amazon.com/ec2/instance-types/ |
| Security Groups Guide | https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-security-groups.html |
| User Data Documentation | https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/user-data.html |
| AWS Free Tier Details | https://aws.amazon.com/free |

### Live Help During the Sprint

📧 **Email:** *(Add group email here)*
📱 **WhatsApp Group:** *(Add link here)*
👥 **Peer Support:** Ask in the WhatsApp group - your classmates have likely hit the same issue

### AWS Support (Free for Account & Billing Issues)

1. Go to https://console.aws.amazon.com/support/home
2. Click **"Create case"**
3. Choose **"Account and billing"**
4. Describe your issue and submit
5. Response time: Usually within 24 hours on the free plan

---

## What's Next - Week 2 Preview

Now that you have launched your first EC2 instance, Week 2 will go deeper:

- **Storage:** Attaching EBS volumes to your instance
- **Networking:** Understanding VPCs, subnets, and routing
- **SSH:** Connecting to your instance and managing it from the terminal
- **Snapshots:** Backing up your instance state

---

> *Cloud Forge Series | AWS Student Builder Group | Egerton University*
> *#AwsStudentBuilders*
