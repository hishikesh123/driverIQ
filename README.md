# DriverIQ — Location-Aware Driver Earnings Intelligence

## 1. Project Overview

**DriverIQ** is a location-aware analytics, machine-learning and local-LLM decision-support system built using historical Uber driver data.

The system answers a practical question:

> **"Where should I drive, when should I drive there, and what earning efficiency can I reasonably expect?"**

Instead of simply analysing historical earnings, DriverIQ combines:

* Time
* Location
* Trip frequency
* Earnings
* Driver utilisation
* Historical earning efficiency
* Local area patterns

to identify **historically productive driving windows and locations**.

A lightweight local Large Language Model (LLM), running through **Ollama**, provides a natural-language interface through which a driver can ask questions such as:

> "Where should I go right now?"

> "Is it worth going to the shopping centre at 6 PM?"

> "What's historically better on Friday evening?"

> "I have three hours tonight. Where should I start?"

The system then combines the LLM with the project's analytical layer to provide an answer based on historical data.

---

# 2. Core Problem

Uber's driver application already provides maps and real-time marketplace information.

However, a driver may still have questions such as:

* How long should I stay in a particular area?
* Is this location historically productive for me?
* What time should I arrive?
* How much could I potentially earn during a particular window?
* Is it better to remain here or move to another area?
* Which nearby shopping centre/town/area has historically produced better earning efficiency?

DriverIQ attempts to answer these questions using **historical driver-side data**.

---

# 3. Central Research Question

> **Can historical driver behaviour and trip-level data be used to estimate the earning efficiency of different locations and time windows, and can those insights be converted into a driver-facing decision-support system?**

### Supporting questions

1. Which locations historically generate the highest earning efficiency?
2. At what times are particular locations most productive?
3. How long should a driver remain in an area before considering another location?
4. Can historical data estimate expected earnings/hour for a location-time combination?
5. Can the system identify locations that are consistently under-utilised?
6. Can a local LLM translate analytical results into natural-language recommendations?
7. How could the system be extended if merchant, rider-demand and marketplace data were available?

---

# 4. Location Intelligence

The central addition to DriverIQ is **location-aware analysis**.

Instead of analysing:

```text
Friday → $/hour
```

the system analyses:

```text
Friday + 6 PM + Location → $/hour
```

For example:

```text
Area A
Friday 5–8 PM
Historical earnings/hour: $29

Area B
Friday 5–8 PM
Historical earnings/hour: $22

Area C
Friday 5–8 PM
Historical earnings/hour: $17
```

The system can therefore identify historically productive **location + time combinations**.

---

# 5. Defining Locations

The project does not necessarily require precise addresses.

Locations can be represented using:

### Option A — Geospatial grids

Convert coordinates into geographic cells.

For example:

```text
Latitude + Longitude
        ↓
Geohash / H3 Cell
        ↓
Location Cluster
```

This provides privacy protection while still allowing spatial analysis.

### Option B — Named areas

If sufficient location information exists, trips can be grouped around:

* Shopping centres
* Major town centres
* CBD areas
* Transport hubs
* Commercial areas
* Entertainment precincts

For example:

```text
Shopping Centre A
Town Centre B
Transport Hub C
CBD Zone D
```

The project can begin with whichever method is easiest given the available data.

---

# 6. Location-Time Windows

Rather than treating an entire day as one observation, DriverIQ divides driving into **time windows**.

Example:

```text
Morning
6–9 AM

Late Morning
9 AM–12 PM

Lunch
12–2 PM

Afternoon
2–5 PM

Evening Peak
5–8 PM

Night
8–11 PM
```

These can later be made more granular if sufficient data exists.

The core analytical unit becomes:

> **Location × Time Window × Day Type**

For example:

```text
Location: Shopping Centre A
Day: Friday
Window: 5–8 PM
```

---

# 7. Location Performance Metrics

Each location/time window can be evaluated using multiple metrics.

### Earnings efficiency

```text
Earnings / Active Hour
```

### Trip density

```text
Trips / Active Hour
```

### Utilisation

```text
Active Time / Online Time
```

### Average trip value

```text
Total Earnings / Number of Trips
```

### Idle time

```text
Online Time - Active Time
```

### Earnings volatility

Measure how consistently the location performs.

This is important because:

> A location generating $30/hour once is different from a location consistently generating around $28–30/hour.

---

# 8. Location Opportunity Score

DriverIQ can create a location-level analytical score.

For example:

```text
Location Opportunity Score

40% Historical $/Hour
25% Utilisation
15% Trips/Hour
10% Consistency
10% Sample Size
```

The weights would be documented as a modelling choice.

The **sample-size component** is particularly important.

A location with only two historical observations should not automatically outrank a location with hundreds of observations.

---

# 9. Confidence / Data Sufficiency

Every location recommendation should include an indication of how much historical evidence exists.

Example:

```text
Shopping Centre A

Expected earnings/hour:
$27–31

Historical sessions:
47

Data confidence:
High
```

Versus:

```text
Shopping Centre B

Expected earnings/hour:
$30–38

Historical sessions:
3

Data confidence:
Low
```

This prevents the system from making overly confident recommendations from limited data.

---

# 10. The "Where Should I Go?" Engine

This becomes one of the central features.

The driver provides:

```text
Current area
Available driving time
Day
Current time
```

DriverIQ analyses nearby historical locations.

Example:

```text
You have 3 hours available.

Historically observed nearby locations:

Location A
Expected: $28/hr
Historical utilisation: 81%
Evidence: 42 sessions

Location B
Expected: $25/hr
Historical utilisation: 76%
Evidence: 61 sessions

Location C
Expected: $21/hr
Historical utilisation: 69%
Evidence: 35 sessions
```

The system can then produce a **data-driven recommendation** based on the historical model.

Importantly, this is a recommendation generated from the user's own historical data—not a claim about current Uber marketplace conditions.

---

# 11. "How Long Should I Stay?" Analysis

This is another important feature.

Instead of simply asking:

> "Where should I go?"

DriverIQ can investigate:

> **"How long is it historically productive to remain in this area?"**

For example:

```text
Shopping Centre A

0–15 min      Low activity
15–30 min     Moderate
30–60 min     High
60–90 min     High
90+ min       Declining utilisation
```

If enough data exists, the system can investigate whether extended waiting periods tend to produce diminishing returns.

This becomes a **driver repositioning problem**:

```text
Current Location
       ↓
Wait
       ↓
Observe performance
       ↓
Historical threshold reached?
       ↓
Yes
       ↓
Consider another location
```

---

# 12. Earnings Forecast

The machine-learning component estimates expected earnings/hour for a specific:

```text
Location
+
Time
+
Day
+
Historical behaviour
```

Potential models:

* Linear Regression
* Random Forest
* Gradient Boosting
* XGBoost

For a one-night prototype, Random Forest or Gradient Boosting is sufficient.

Example:

```text
Input

Location: Town Centre A
Day: Saturday
Time: 6 PM
Duration: 3 hours

↓

Model

Expected earnings/hour:
$26.80

Expected earnings:
$80.40
```

The result should be presented as an estimate with uncertainty rather than a guaranteed earning amount.

---

# 13. Local LLM Integration

DriverIQ will include a lightweight local LLM using:

**Ollama**

Possible models include a small Llama-family or other locally supported instruction model.

The LLM will **not be responsible for calculating the numbers**.

Instead:

```text
Raw Data
   ↓
Python Analytics
   ↓
ML Model
   ↓
Structured Results
   ↓
Local LLM
   ↓
Natural Language Response
```

This is an important architectural decision.

The LLM acts as the **reasoning/interface layer**, while Python remains responsible for numerical analysis.

---

# 14. Example LLM Interaction

### User

> "I have three hours tonight. Where should I go?"

### Analytics engine

```text
Current time: 5:30 PM

Candidate A:
Expected $/hour = $29.40
Historical utilisation = 84%
Observations = 53

Candidate B:
Expected $/hour = $26.20
Historical utilisation = 79%
Observations = 67

Candidate C:
Expected $/hour = $22.80
Historical utilisation = 71%
Observations = 44
```

### Local LLM

The LLM converts those structured results into a concise explanation:

> "Based on your historical data, Candidate A has the strongest historical earning efficiency for this time window. You have 53 observations there and an estimated $29.40/hour. Candidate B is the next strongest option. These are historical estimates and don't account for current demand or supply."

---

# 15. Natural Language Questions

The LLM interface could support questions such as:

### Time

> "When should I drive tonight?"

### Location

> "Which nearby area has historically performed best on Saturday evenings?"

### Duration

> "Is it worth staying here for another hour?"

### Comparison

> "Compare Town Centre A and Shopping Centre B."

### Historical analysis

> "What was my best earning location last month?"

### Planning

> "I have five hours available tomorrow. How should I split my driving time?"

### Explanation

> "Why does this location score highly?"

---

# 16. LLM Architecture

```text
                    DRIVER
                      │
                      ▼
              Natural Language
                 Question
                      │
                      ▼
              ┌──────────────┐
              │ Local LLM    │
              │   Ollama     │
              └──────┬───────┘
                     │
              Intent / Parameters
                     │
                     ▼
             Analytics Engine
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
   Historical     ML Model    Location Data
      Data
        │            │            │
        └────────────┼────────────┘
                     ▼
              Structured Result
                     │
                     ▼
                 Local LLM
                     │
                     ▼
              Natural Language
                  Response
```

---

# 17. Merchant / Rider Data

The project does **not** require merchant-side or rider-side data to demonstrate the concept.

The available driver data can provide:

* Driver location
* Trip frequency
* Trip timing
* Earnings
* Utilisation
* Historical performance

These can be used to construct a **driver-side observational model**.

However, there is an important limitation:

> A driver's historical earnings cannot directly reveal the underlying level of rider demand or merchant activity.

For example, if a shopping centre produces $30/hour historically, we cannot determine from driver data alone whether this was caused by:

* High rider demand
* Low driver supply
* Dynamic pricing
* Merchant concentration
* Local events
* Weather
* Trip distance
* Other marketplace factors

Therefore, DriverIQ treats these factors as **latent/unobserved marketplace variables**.

---

# 18. Marketplace Extension

If richer Uber marketplace data were available, the system could eventually incorporate:

### Rider demand

* Request volume
* Request density
* Request-to-driver ratio

### Driver supply

* Active drivers
* Available drivers
* Driver density

### Merchant activity

For Uber Eats:

* Merchant order volume
* Restaurant density
* Preparation time
* Merchant wait time

### External variables

* Weather
* Public events
* Holidays
* Traffic
* Road closures

This would allow:

```text
Driver Data
     +
Rider Demand
     +
Driver Supply
     +
Merchant Activity
     +
External Variables
          ↓
Marketplace State
          ↓
Expected Driver Opportunity
```

The current project establishes the analytical framework without requiring access to those additional datasets.

---

# 19. Potential Advanced Feature

A future version could calculate a **Location Opportunity Index**:

```text
Opportunity =
Expected Earnings
×
Expected Utilisation
×
Confidence
```

This could produce a map:

```text
                    LOCATION MAP

             ┌──────────────────────┐
             │                      │
             │     Area A           │
             │      HIGH            │
             │                      │
             │             Area B    │
             │              MED      │
             │                      │
             │  Area C              │
             │   LOW                │
             │                      │
             └──────────────────────┘
```

The map could be implemented using:

* Folium
* Plotly Mapbox
* Kepler.gl
* Streamlit map components

---

# 20. System Architecture

```text
                    ┌───────────────────┐
                    │ Historical Uber   │
                    │ Driver Data       │
                    └─────────┬─────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │ Data Processing    │
                    │ Pandas / Python    │
                    └─────────┬─────────┘
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
             Feature Engineering    Geospatial
                    │                Processing
                    │                   │
                    └─────────┬─────────┘
                              ▼
                    ┌───────────────────┐
                    │ Analytics Engine   │
                    └─────────┬─────────┘
                              │
               ┌──────────────┴──────────────┐
               ▼                             ▼
        Historical Analysis             ML Prediction
               │                             │
               └──────────────┬──────────────┘
                              ▼
                    ┌───────────────────┐
                    │ Recommendation     │
                    │ Engine             │
                    └─────────┬─────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │ Ollama Local LLM   │
                    └─────────┬─────────┘
                              │
                              ▼
                    ┌───────────────────┐
                    │ Streamlit UI      │
                    └───────────────────┘
```

---

# 21. Technology Stack

## Data

* Python
* Pandas
* NumPy

## Machine Learning

* Scikit-learn
* Optional XGBoost

## Geospatial

* GeoPandas
* H3 or geohash
* Folium / Plotly

## Visualisation

* Plotly
* Matplotlib

## Application

* Streamlit

## Local AI

* Ollama
* Small instruction-tuned LLM

## Development

* Jupyter
* Git
* GitHub

---

# 22. MVP — What Can Be Built Tonight?

The project should be deliberately scoped.

### Phase 1 — Data

* Import Uber archive
* Identify useful columns
* Clean timestamps
* Clean earnings
* Clean location information

### Phase 2 — Location analysis

Create:

```text
Location
+
Day
+
Time Window
```

and calculate:

* Earnings/hour
* Trips/hour
* Utilisation
* Number of observations

### Phase 3 — Visualisation

Build:

1. Earnings by time
2. Earnings by location
3. Location × time heatmap
4. Map of historical performance

### Phase 4 — Prediction

Build one model:

> Expected earnings/hour

### Phase 5 — Recommendation engine

Input:

```text
Current/selected location
Day
Time
Available hours
```

Output:

```text
Candidate locations
Expected earnings/hour
Historical utilisation
Evidence count
```

### Phase 6 — Ollama

Connect the recommendation engine to a small local LLM.

### Phase 7 — Streamlit

Create a simple interface.

---

# 23. Minimum Viable Product

If time becomes limited, the MVP should contain only:

```text
✓ Uber data cleaning
✓ Location clustering
✓ Time-window analysis
✓ Earnings/hour
✓ Location performance
✓ Heatmap
✓ Simple prediction model
✓ "Where should I go?" recommendation
✓ Ollama natural-language interface
✓ Streamlit dashboard
✓ GitHub README
```

The merchant/rider-demand extension can remain in the **Future Work** section.

---

# 24. Example Final User Experience

The driver opens DriverIQ.

```text
Current time: 5:42 PM
Available driving time: 4 hours
```

The application analyses historical data.

```text
Nearby Historical Opportunities

┌───────────────────────────────────┐
│ Town Centre A                     │
│ $28.40/hr                         │
│ Utilisation: 83%                 │
│ Evidence: 48 sessions             │
├───────────────────────────────────┤
│ Shopping Centre B                 │
│ $25.70/hr                         │
│ Utilisation: 79%                 │
│ Evidence: 64 sessions             │
├───────────────────────────────────┤
│ Area C                            │
│ $21.90/hr                         │
│ Utilisation: 68%                 │
│ Evidence: 39 sessions             │
└───────────────────────────────────┘
```

The driver asks:

> "What should I do?"

Ollama responds using the structured analytical results.

The driver then asks:

> "What if I stay for two hours?"

The system recalculates the expected outcome.

That creates a small **interactive decision-support product**, rather than just a dashboard.

---

# 25. Responsible Interpretation

DriverIQ should never claim:

> "This location WILL make you $30/hour."

Instead:

> "Historical observations for this location/time window indicate an estimated earning efficiency of approximately $30/hour."

The distinction is important because current marketplace conditions can change.

The model does not directly observe:

* Current demand
* Current driver supply
* Current incentives
* Current surge/dynamic pricing
* Current merchant activity
* Current traffic
* Current events

Therefore, DriverIQ is a **historical decision-support system**, not a real-time earnings guarantee.

---

# 26. Final Project Positioning

DriverIQ can be positioned as:

> **A location-aware driver decision-support system combining behavioural analytics, geospatial analysis, machine learning and local LLMs to investigate historical earning efficiency across time and location.**

The project demonstrates:

**Data Engineering**

→ **EDA**

→ **Behavioural Analytics**

→ **Geospatial Analytics**

→ **Machine Learning**

→ **Recommendation Systems**

→ **LLM Integration**

→ **Product Development**

→ **Marketplace Thinking**

---

# 27. Portfolio Pitch

> **DriverIQ transforms historical Uber driver data into a location-aware decision-support system. It analyses driver behaviour and historical earning patterns across time and geography, estimates earning efficiency for different location-time windows, and uses a local Ollama LLM to allow drivers to interact with the analytical system using natural language. The project also explores how the system could evolve from driver-side analytics into marketplace intelligence by incorporating demand, supply, merchant and external contextual data.**

---

# 28. Project Goal

The ultimate goal is not simply to answer:

> **"How much did I earn?"**

It is to build a prototype capable of answering:

> **"Given what I know from my historical data, where and when has it historically been most productive to drive, how long should I consider staying, and what evidence supports that recommendation?"**
