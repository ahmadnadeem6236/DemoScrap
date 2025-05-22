from playwright.async_api import async_playwright
import pandas as pd
import re
import emoji
import logging
import os
import asyncio
import random
import time
from typing import List, Dict, Optional, Any
from http import HTTPStatus
from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import Error as PlaywrightError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scraper.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

class RateLimiter:
    """Simple rate limiter to prevent being blocked"""
    def __init__(self, min_delay: float = 2.0, max_delay: float = 3.0):
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.last_request_time = 0

    async def wait(self):
        """Wait a random amount of time between requests"""
        now = time.time()
        elapsed = now - self.last_request_time
        delay = random.uniform(self.min_delay, self.max_delay)

        if elapsed < delay:
            wait_time = delay - elapsed
            logger.debug(f"Rate limiting: waiting {wait_time:.2f} seconds")
            await asyncio.sleep(wait_time)

        self.last_request_time = time.time()

class ReviewValidator:
    """Validates and deduplicates review data"""
    def __init__(self):
        self.seen_reviews = set()

    def validate_review(self, review: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Validate review data and return None if invalid"""
        # Check for required fields
        required_fields = ["Hospital", "Reviewer", "Rating", "Review"]
        for field in required_fields:
            if field not in review or not review[field]:
                logger.warning(f"Missing required field: {field}")
                return None

        # Check review text length
        if len(review["Review"]) < 5:
            logger.debug(f"Review too short: {review['Review']}")
            return None

        # Deduplicate using a hash of content
        review_hash = hash(f"{review['Hospital']}:{review['Reviewer']}:{review['Review']}")
        if review_hash in self.seen_reviews:
            logger.debug(f"Duplicate review: {review['Review'][:30]}...")
            return None

        self.seen_reviews.add(review_hash)
        return review

async def initialize_browser():
    """Initialize Playwright browser"""
    try:
        playwright = await async_playwright().start()
        browser = await playwright.chromium.launch(
            headless=False,
            args=['--disable-blink-features=AutomationControlled']  # Help avoid detection
        )
        context = await browser.new_context(
            user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/96.0.4664.110 Safari/537.36',
            viewport={'width': 1280, 'height': 800}
        )
        # Add stealth settings to avoid detection
        await context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => false
            });
        """)
        page = await context.new_page()
        return playwright, browser, page
    except PlaywrightError as e:
        logger.error(f"Failed to initialize browser: {str(e)}")
        raise

async def search_google_maps(page, location, rate_limiter):
    """Search for hospitals in the specified location"""
    try:
        await rate_limiter.wait()

        # Set a longer navigation timeout
        page.set_default_navigation_timeout(6000)  # 60 seconds

        await page.goto("https://www.google.com/maps")

        # Wait for the search box to be available
        await page.wait_for_selector("input[id='searchboxinput']", timeout=3000)

        search_box = page.locator("input[id='searchboxinput']")
        search_query = f"top hospitals in {location}"
        logger.info(f"Searching for: {search_query}")

        await search_box.fill(search_query)
        await search_box.press("Enter")

        # Wait for results to appear instead of networkidle
        logger.info("Waiting for search results...")
        await page.wait_for_selector("div[class*='Nv2PK']", timeout=45000)
        logger.info("Search results loaded")

    except PlaywrightTimeoutError as e:
        logger.error(f"Timeout when searching Google Maps: {str(e)}")
        raise
    except PlaywrightError as e:
        logger.error(f"Error searching Google Maps: {str(e)}")
        raise

async def search_google_location(page, location, rate_limiter):
    try:
        await rate_limiter.wait()

        # Set a longer navigation timeout
        page.set_default_navigation_timeout(60000)  # 60 seconds

        # Use domcontentloaded instead of networkidle
        await page.goto(location, wait_until="domcontentloaded")

        # Wait for a reasonable amount of time for content to load
        await asyncio.sleep(3)

    except PlaywrightTimeoutError as e:
        logger.error(f"Timeout when opening hospital URL: {str(e)}")
        raise
    except PlaywrightError as e:
        logger.error(f"Error opening hospital URL: {str(e)}")
        raise

async def get_hospital_list(page, rate_limiter, max_hospitals=10):
    """Get a list of hospitals from search results"""
    hospitals = []
    try:
        # Wait for results to be visible
        await page.wait_for_selector("div[class*='Nv2PK']")

        # Scroll to load more results - more aggressively
        logger.info("Scrolling to load more hospital results...")
        for i in range(5):  # Increased from 3 to 5 scrolls
            logger.info(f"Scroll {i+1}/5")
            # More dramatic scrolling
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(random.uniform(2.0, 3.0))  # Longer wait between scrolls

            # Try to find scrollable container and scroll it too
            try:
                await page.evaluate("""
                    const scrollableContainers = Array.from(document.querySelectorAll('div[role="feed"], div[jsaction*="scroll"]'));
                    if (scrollableContainers.length > 0) {
                        scrollableContainers.forEach(container => {
                            container.scrollTop = container.scrollHeight;
                        });
                    }
                """)
            except:
                pass

        # Get hospital listings
        hospital_elements =  page.locator("div[class*='Nv2PK']")
        count = await hospital_elements.count()
        logger.info(f"Found {count} hospital listings")

        for i in range(min(count, max_hospitals)):
            try:
                element = await hospital_elements.nth(i).element_handle()

                name_element = await element.query_selector("div.qBF1Pd")
                if not name_element:
                    continue

                hospital_name = await name_element.inner_text()

                href_element = await element.query_selector("a.hfpxzc")
                if not href_element:
                    continue

                hospital_href = await href_element.get_attribute("href")

                address_element = await element.query_selector("div.W4Efsd:nth-child(1)")  # More specific selector for address
                hospital_address = ""
                if address_element:
                    address_text = await address_element.inner_text()
                    # Split by newlines and get the second line which contains the actual address
                    address_lines = address_text.split('\n')
                    if len(address_lines) >= 2:
                        # Take the second line which contains the actual address
                        hospital_address = address_lines[1].strip()
                    elif address_lines:
                        # If there's only one line, try to remove common hospital type prefixes
                        address = address_lines[0].strip()
                        # Remove common hospital type prefixes
                        prefixes_to_remove = ["General hospital", "Private hospital", "University hospital", "State hospital"]
                        for prefix in prefixes_to_remove:
                            if address.lower().startswith(prefix.lower()):
                                address = address[len(prefix):].strip()
                        hospital_address = address

                if hospital_name and hospital_href:
                    hospital_info = {
                        'name': hospital_name,
                        'address': hospital_address,
                        'href': hospital_href
                    }
                    hospitals.append(hospital_info)
                    logger.info(f"Added hospital: {hospital_name}")
            except PlaywrightError as e:
                logger.warning(f"Error getting hospital info: {str(e)}")
                continue

    except PlaywrightTimeoutError as e:
        logger.error(f"Timeout getting hospital list: {str(e)}")
    except PlaywrightError as e:
        logger.error(f"Error getting hospital list: {str(e)}")

    return hospitals

def clean_text(text):
    # Remove emojis
    text = emoji.replace_emoji(text, replace='')
    # Remove extra whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text

async def scrape_reviews(page, hospital_name, rate_limiter, validator, max_reviews=60):
    reviews = []
    try:
        # Locate and click the reviews section
        logger.info(f"Opening reviews for: {hospital_name}")
        logger.info("Searching for reviews section")

        # Take a screenshot to see the current state
        # await page.screenshot(path=f"hospital_page_{hospital_name.replace(' ', '_')}.png")

        # First wait for the page to stabilize
        await asyncio.sleep(3)

        # Try multiple approaches to find the reviews section
        found_reviews = False

        # Approach 1: Look for tab with "Reviews" text
        try:
            logger.info("Trying to find Reviews tab...")
            review_tab = page.get_by_role('tab', name="Reviews")
            if await review_tab.count() > 0:
                logger.info("Found Reviews tab")
                await rate_limiter.wait()
                await review_tab.click()
                await asyncio.sleep(2)
                found_reviews = True
        except PlaywrightError as e:
            logger.warning(f"Could not find Reviews tab: {str(e)}")

        # Approach 2: Look for elements containing review text
        if not found_reviews:
            logger.info("Looking for review elements directly...")
            review_selectors = [
                "div[class*='jJc9Ad']",   # Original selector
                "div[data-review-id]",    # Elements with review IDs
                "div[class*='review']",   # Classes containing 'review'
                "div[class*='rating']",   # Classes containing 'rating'
                "div[class*='star']"      # Classes containing 'star'
            ]

            for selector in review_selectors:
                try:
                    elements = page.locator(selector)
                    count = await elements.count()
                    if count > 0:
                        logger.info(f"Found {count} review elements with selector: {selector}")
                        found_reviews = True
                        break
                except PlaywrightError:
                    continue

        # Approach 3: Try to click on any element that might reveal reviews
        if not found_reviews:
            logger.info("Trying to click on elements that might reveal reviews...")
            potential_review_triggers = [
                "button:has-text('Reviews')",
                "button:has-text('Review')",
                "a:has-text('Reviews')",
                "div:has-text('Reviews')",
                "span:has-text('Reviews')"
            ]

            for selector in potential_review_triggers:
                try:
                    elements = page.locator(selector)
                    count = await elements.count()
                    if count > 0:
                        logger.info(f"Found potential review trigger: {selector}")
                        await elements.first.click()
                        await asyncio.sleep(2)
                        found_reviews = True
                        break
                except PlaywrightError:
                    continue

        if not found_reviews:
            logger.warning("Could not find the reviews section, trying to continue anyway")
            # Take another screenshot to see current state
            await page.screenshot(path=f"no_reviews_found_{hospital_name.replace(' ', '_')}.png")

        # Scroll to load potential reviews, even if we couldn't find a specific tab
        logger.info("Scrolling to find reviews...")
        for i in range(5):  # Increased from 3 to 5 scrolls
            logger.info(f"Review scroll {i+1}/5")

            # Try multiple scrolling techniques
            # 1. Standard mouse wheel
            await page.mouse.wheel(0, 3000)
            await asyncio.sleep(1.0)

            # 2. JavaScript scrolling
            try:
                # Try to find and scroll the reviews container
                await page.evaluate("""
                    // Try to find review containers
                    const reviewContainers = Array.from(document.querySelectorAll(
                        'div[role="feed"], div[jsaction*="scroll"], div[data-review-id], div[class*="review"], div[class*="scroll"]'
                    ));

                    if (reviewContainers.length > 0) {
                        reviewContainers.forEach(container => {
                            container.scrollTop = container.scrollHeight;
                        });
                    } else {
                        // If no specific container, scroll the whole page
                        window.scrollTo(0, document.body.scrollHeight);
                    }
                """)
            except:
                pass

            # Wait after scrolling
            await asyncio.sleep(random.uniform(1.5, 2.5))

            # 3. Check if we have enough reviews already, if so we can stop scrolling
            try:
                for selector in ["div[class*='jJc9Ad']", "div[class*='review']", "div[data-review-id]"]:
                    count = await page.locator(selector).count()
                    if count >= max_reviews:
                        logger.info(f"Found {count} reviews already, stopping scrolling")
                        break
            except:
                pass

        # Try multiple selectors for finding review elements
        review_element_selectors = [
            "div[class*='jJc9Ad']",        # Original selector
            "div[data-review-id]",         # Elements with review ID
            "div[class*='review']",        # Classes with 'review'
            ".review-container",           # Common review container class
            "div[class*='comment']",       # Comment sections
            "div:has(span[aria-label*='stars'])" # Elements containing star ratings
        ]

        review_elements = None
        used_selector = None

        for selector in review_element_selectors:
            try:
                elements = page.locator(selector)
                count = await elements.count()
                if count > 0:
                    logger.info(f"Found {count} review elements with selector: {selector}")
                    review_elements = elements
                    used_selector = selector
                    break
            except PlaywrightError:
                continue

        if not review_elements:
            logger.warning("Could not find any review elements")
            return reviews

        count = await review_elements.count()
        logger.info(f"Found {count} reviews with selector: {used_selector}")

        # Extract reviews using the found selector
        for i in range(min(count, max_reviews)):
            try:
                element = await review_elements.nth(i).element_handle()

                # Try multiple selectors for reviewer name
                reviewer = None
                for name_selector in ["div[class*='d4r55']", "div[class*='author']", "span[class*='name']", "div[class*='profile']"]:
                    try:
                        name_elem = await element.query_selector(name_selector)
                        if name_elem:
                            reviewer = await name_elem.inner_text()
                            if reviewer:
                                break
                    except:
                        pass

                if not reviewer:
                    reviewer = f"Anonymous Reviewer {i+1}"

                # Try multiple selectors for rating
                rating = None
                for rating_selector in ["span[aria-label*='star']", "span[class*='rating']", "div[class*='star']", "span[aria-label]"]:
                    try:
                        rating_elem = await element.query_selector(rating_selector)
                        if rating_elem:
                            rating = await rating_elem.get_attribute("aria-label")
                            if not rating:
                                rating = await rating_elem.inner_text()
                            if rating:
                                break
                    except:
                        pass

                if not rating:
                    rating = "No rating"

                # Try multiple selectors for review text
                review_text = None
                for text_selector in ["span[class*='wiI7pd']", "div[class*='review-text']", "div[class*='content']", "span[class*='review']"]:
                    try:
                        text_elem = await element.query_selector(text_selector)
                        if text_elem:
                            review_text = await text_elem.inner_text()
                            if review_text:
                                break
                    except:
                        pass

                if not review_text:
                    try:
                        # Try to get any text content as a last resort
                        review_text = await element.inner_text()
                    except:
                        review_text = "No review text available"

                review_data = {
                    "Hospital": hospital_name,
                    "Reviewer": clean_text(reviewer),
                    "Rating": rating,
                    "Review": clean_text(review_text)
                }

                # Validate the review
                validated_review = validator.validate_review(review_data)
                if validated_review:
                    reviews.append(validated_review)

            except PlaywrightError as e:
                logger.warning(f"Error extracting review: {str(e)}")
                continue

    except PlaywrightTimeoutError as e:
        logger.error(f"Timeout when scraping reviews: {str(e)}")
        # Take a screenshot for debugging
        try:
            await page.screenshot(path=f"error_timeout_reviews_{hospital_name.replace(' ', '_')}.png")
        except:
            pass
    except PlaywrightError as e:
        logger.error(f"Error during review scraping: {str(e)}")
        try:
            await page.screenshot(path=f"error_reviews_{hospital_name.replace(' ', '_')}.png")
        except:
            pass

    # Log the results
    logger.info(f"Extracted {len(reviews)} valid reviews for {hospital_name}")
    return reviews

def save_reviews_to_csv(reviews, hospital_name, location):
    if not reviews:
        logger.warning(f"No valid reviews to save for {hospital_name}")
        return

    try:
        # Create a directory for the location if it doesn't exist
        location_dir = f"hospital_reviews_{location.replace(' ', '_')}"
        os.makedirs(location_dir, exist_ok=True)

        # Create a safe filename from the hospital name
        safe_hospital_name = re.sub(r'[^a-zA-Z0-9]', '_', hospital_name)
        filename = os.path.join(location_dir, f"{safe_hospital_name}_reviews.csv")

        df = pd.DataFrame(reviews)
        df.to_csv(filename, index=False, encoding='utf-8')
        logger.info(f"Reviews saved to {filename}")
    except IOError as e:
        logger.error(f"Error saving reviews to CSV: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error saving CSV: {str(e)}")

def save_hospital_list_to_csv(hospitals, location):
    """Save the list of hospitals to a CSV file"""
    if not hospitals:
        logger.warning(f"No hospitals to save for {location}")
        return

    try:
        # Create a directory for the location if it doesn't exist
        location_dir = f"hospital_reviews_{location.replace(' ', '_')}"
        os.makedirs(location_dir, exist_ok=True)

        # Create a filename for the hospital list
        filename = os.path.join(location_dir, f"hospital_list_{location.replace(' ', '_')}.csv")

        # Add an index column to the data
        hospital_data = []
        for i, hospital in enumerate(hospitals, 1):
            hospital_data.append({
                'Index': i,
                'Hospital Name': hospital['name'],
                'Hospital Address': hospital['address'],
                'Google Maps URL': hospital['href']
            })

        df = pd.DataFrame(hospital_data)
        df.to_csv(filename, index=False, encoding='utf-8')
        logger.info(f"Hospital list saved to {filename}")
    except IOError as e:
        logger.error(f"Error saving hospital list to CSV: {str(e)}")
    except Exception as e:
        logger.error(f"Unexpected error saving hospital list CSV: {str(e)}")

async def main():
    location = "Istanbul, Turkey"  # You can change this to any location
    rate_limiter = RateLimiter(min_delay=2.0, max_delay=5.0)
    validator = ReviewValidator()

    # Initialize browser
    playwright = browser = page = None
    try:
        playwright, browser, page = await initialize_browser()

        # Search for hospitals
        await search_google_maps(page, location, rate_limiter)

        # Get list of hospitals
        hospitals = await get_hospital_list(page, rate_limiter)

        # Validate hospitals list
        if not hospitals:
            logger.warning(f"No hospitals found in {location}")
            return

        # Save the hospital list to CSV
        save_hospital_list_to_csv(hospitals, location)

        # Scrape reviews for each hospital
        for hospital in hospitals:
            try:
                # Search for the specific hospital
                await search_google_location(page, hospital['href'], rate_limiter)
                hospital_reviews = await scrape_reviews(page, hospital['name'], rate_limiter, validator)

                # Save reviews for this hospital
                save_reviews_to_csv(hospital_reviews, hospital['name'], location)

                # Add a random delay between hospitals
                await asyncio.sleep(random.uniform(3.0, 7.0))

            except Exception as e:
                logger.error(f"Failed to process hospital {hospital['name']}: {str(e)}")
                continue

    except Exception as e:
        logger.error(f"Unhandled exception in main: {str(e)}")
    finally:
        # Cleanup
        if page:
            await page.wait_for_timeout(2000)
        if browser:
            await browser.close()
        if playwright:
            await playwright.stop()

if __name__ == "__main__":
    asyncio.run(main())
