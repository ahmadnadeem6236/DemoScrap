# Google Maps Hospital Reviews Scraper

This project is a Python-based web scraper that uses Playwright to extract hospital reviews from Google Maps. It is designed to automate the process of collecting reviews for hospitals in a specific location.

## Features

- Searches for hospitals on Google Maps based on a query.
- Extracts hospital names, ratings, addresses, and reviews.
- Handles scrolling to load more reviews dynamically.
- Saves the scraped data in a structured format (e.g., JSON).
- Includes error handling for common issues like timeouts and missing elements.

## Requirements

- Python 3.8 or higher
- Playwright
- BeautifulSoup (for parsing HTML)
- Other dependencies listed in `requirements.txt`

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/your-username/demoscrap.git
   cd GoogleReviewScrapper
   ```
2. Install the required packages:
   ```bash
   pip install -r requirements.txt
   ```
3. Install Playwright browsers:

   ```bash
   playwright install
   ```

4. The scraped data will be saved in a JSON file named `hospital_reviews.json`.
5. You can customize the search query and location in the `scraper.py` file.

## Usage

Update the configuration variables in main.py:

BASE_URL: The base URL for Google Maps.
SEARCH_QUERY: The search term (e.g., "hospitals in New Delhi").
NUM_HOSPITALS_TO_SCRAPE: Number of hospitals to process.
MAX_REVIEWS_PER_HOSPITAL: Maximum number of reviews to scrape per hospital.
Run the scraper:

```bash
python main.py
```

## Project Structure

demoscrap/
├── [main.py](http://_vscodecontentref_/1) # Main script for scraping
├── requirements.txt # Python dependencies
├── [README.md](http://_vscodecontentref_/2) # Project documentation
└── other files... # Additional scripts or resources
