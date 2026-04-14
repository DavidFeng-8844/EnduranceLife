# EnduranceLife Oral Presentation Script (5 Minutes)

> **Preparation Tips:** 
> - Speak at a comfortable, moderate pace. 
> - 5 minutes is about 650-700 words. This script is perfectly tailored to fit that window.
> - Have your browser open with the Swagger UI (`/docs`) ready for the live demo right after slide 6.

---

## Slide 1: Title
*(0:00 - 0:15)*

"Good [morning/afternoon] everyone. My name is David Feng, and today I’m excited to present my final project: **EnduranceLife**, an advanced physiological and training analytics Web API. Simply put, this is a secure, data-driven backend designed for serious endurance athletes."

---

## Slide 2: Project Vision & Context
*(0:15 - 1:00)*

"The core problem I wanted to solve is that most popular fitness platforms out there, like Strava, are heavily optimized for social networking. They often neglect the deep, analytical correlation between an athlete's physical training and their subjective lifestyle variables—like sleep quality and mental fatigue.

To solve this, I built EnduranceLife. It shifts the focus entirely to objective analytics. As you'll see, the ultimate goal of my project was to seamlessly ingest complex binary training files, process them rapidly, and combine them with daily subjective metrics to give athletes accurate race pacing predictions and holistic insights."

---

## Slide 3: System Architecture & Stack
*(1:00 - 1:45)*

"To build a resilient platform, I thoughtfully selected a modern and scalable Python tech stack. 

For the backend framework, I used **FastAPI**. Its asynchronous capabilities combined with **Pydantic V2** allowed me to enforce incredibly strict data validation while generating automatic API documentation. 

For the database layer, I integrated **SQLAlchemy 2.0**. A major technical achievement here is the dual-database setup. During local development and testing, the system seamlessly runs on a lightning-fast in-memory SQLite database. However, when deployed to the cloud on Render, it automatically hooks into a highly scalable PostgreSQL instance without any code changes."

---

## Slide 4: Data Pipeline & Innovation
*(1:45 - 2:45)*

"One of the biggest innovations in EnduranceLife is its data pipeline. 

Usually, APIs expect users to manually map out complex JSON payloads. Instead, I built a smart ingestion endpoint that directly accepts native **binary `.fit` files**—the global standard used by Garmin and Coros watches. The backend instantly extracts bounding timestamps, distances, and calculates parameters entirely on its own.

Additionally, I implemented a 'Composite-Key Smart Upsert' for the daily lifestyle metrics. When a user logs their sleep or fatigue, the frontend doesn't need to know the database row ID. It simply tells the API 'this is the data for today', and the backend natively handles whether it needs to insert a new row or update an existing one."

---

## Slide 5: The Analytics Engine
*(2:45 - 3:45)*

"The heart of the project is the Analytics Engine. 

To prevent memory and CPU bloat in Python, I heavily optimized the querying logic to push computational heavy-lifting down to the SQL engine. 

For instance, the database automatically filters out GPS anomalies—like physically impossible paces—before aggregating Personal Records. Furthermore, I successfully implemented the famous Jack Daniels VO2-Velocity quadratic formula directly into the API, allowing it to predict race finish times based on the athlete's continuously evolving fitness level.

Finally, utilizing advanced SQL `CASE` and `JOIN` expressions, the system automatically groups activities into buckets—such as grouping runs by Cold, Moderate, or Hot temperatures—to reveal how environmental friction impacts an athlete's cardiovascular performance."

---

## Slide 6: Cloud Deployment & Evidence
*(3:45 - 4:15)*

"As proof of a successful DevOps pipeline, the entire EnduranceLife API is currently live in a production environment on Render. 

The application is securely connected to a persistent, managed PostgreSQL instance shown here on the left. On the right, you can see live server logs and the functional Swagger UI. To ensure this demo remains robust, I engineered an automatic Start Command that dynamically reseeds the PostgreSQL database with historical metadata in the event of an ephemeral server reset."

---

## Slide 7: Security, Testing & Demo Transition
*(4:15 - 5:00)*

"Lastly, dealing with personal health data requires exceptional security. 

EnduranceLife is protected by a JSON Web Token (JWT) architecture. More importantly, I engineered a **Zero-Trust Data Isolation mechanism**. To protect against IDOR vulnerabilities, the system ignores any User IDs sent by the client. Every single database transaction is strictly mapped to the cryptographic token held by the current user.

I've ensured the stability of this logic with a comprehensive test suite of **77 automated pytest cases** that run entirely in-memory, achieving robust coverage against edge cases.

*(Pause briefly, switch context to browser)*

That concludes the architecture overview. I'd now like to pivot and show you a very brief live demonstration of the Swagger UI where we can see these systems in action..." 

*(5:00)* 
*(Begin your 15-30 second demo of logging in and fetching the Analytics Trends)*
