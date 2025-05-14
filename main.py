import time
import json
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from bs4 import BeautifulSoup # Import BeautifulSoup

# --- Configuration ---
SEARCH_QUERY = "hospitals in New Delhi"
NUM_HOSPITALS_TO_SCRAPE = 5  # Number of hospitals to scrape from the search results
MAX_REVIEWS_PER_HOSPITAL = 10 # Max reviews to fetch per hospital (increased a bit)
HEADLESS_BROWSER = False # Set to True to run browser in background, False to watch it
BASE_URL = "https://www.google.com/maps"

# --- Helper Functions ---
def handle_cookie_consent(page):
    """Attempts to click common cookie consent buttons."""
    consent_selectors = [
        "button[aria-label*='Accept all']",
        "button[aria-label*='Reject all']",
        "form[action*='consent'] button",
        "div[class*='consent'] button[class*='action']",
        "button:has-text('Accept')",
        "button:has-text('I agree')",
        "button:has-text('Agree')",
    ]
    for selector in consent_selectors:
        try:
            button = page.query_selector(selector)
            if button and button.is_visible():
                print(f"Attempting to click consent button: {selector}")
                button.click(timeout=5000)
                page.wait_for_load_state('networkidle', timeout=5000)
                print("Consent button clicked.")
                return True
        except PlaywrightTimeoutError:
            print(f"Timeout clicking consent button: {selector}")
        except Exception as e:
            print(f"Could not click consent button {selector}: {e}")
    print("No identifiable cookie consent button found or clicked.")
    return False

# --- Main Scraping Logic ---
def scrape_google_maps_reviews():
    """
    Main function to scrape hospital reviews from Google Maps.
    Uses Playwright for navigation/interaction and BeautifulSoup for parsing review details.
    Includes improved scrolling logic for reviews.
    """
    all_hospitals_data = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=HEADLESS_BROWSER, args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/98.0.4758.102 Safari/537.36",
            java_script_enabled=True,
            geolocation={"longitude": 77.2090, "latitude": 28.6139} # New Delhi coordinates
        )
        page = context.new_page()

        try:
            print(f"Navigating to {BASE_URL}...")
            page.goto(BASE_URL, timeout=60000, wait_until="domcontentloaded")
            
            handle_cookie_consent(page)
            time.sleep(2) 

            print(f"Searching for: '{SEARCH_QUERY}'...")
            search_box_selector = "input#searchboxinput"
            page.wait_for_selector(search_box_selector, timeout=20000)
            page.fill(search_box_selector, SEARCH_QUERY)
            
            search_button_selector = "button#searchbox-searchbutton"
            page.wait_for_selector(search_button_selector, timeout=10000)
            page.click(search_button_selector)
            print("Search submitted.")

            results_list_selector = "div[role='feed']" 
            page.wait_for_selector(results_list_selector, timeout=30000) 
            print("Search results loaded.")
            time.sleep(5) 

            hospital_entry_selectors = [
                f"{results_list_selector} div[role='article'] a[href*='/maps/place/']",
                f"{results_list_selector} div > div > a[href*='/maps/place/']",
                "a.hfpxzc" 
            ]
            
            hospital_elements = []
            for selector in hospital_entry_selectors:
                hospital_elements = page.query_selector_all(selector)
                if hospital_elements:
                    print(f"Found {len(hospital_elements)} potential hospital entries using selector: {selector}")
                    break
            
            if not hospital_elements:
                print("Could not find hospital entries. Selectors might need updating.")
                # print(f"Page content for debug:\n{page.content()}") # Uncomment for extensive debugging
                return []

            hospitals_to_process = hospital_elements[:NUM_HOSPITALS_TO_SCRAPE]
            print(f"Processing the first {len(hospitals_to_process)} hospitals...")

            for i in range(len(hospitals_to_process)):
                hospital_data = {"hospital_name": "N/A", "reviews": []}
                
                current_hospital_elements = []
                for sel in hospital_entry_selectors: # Re-fetch to avoid stale elements
                    current_hospital_elements = page.query_selector_all(sel)
                    if current_hospital_elements and len(current_hospital_elements) > i:
                        break
                
                if not current_hospital_elements or len(current_hospital_elements) <= i:
                    print(f"Could not re-fetch hospital element at index {i}. Skipping.")
                    continue

                hospital_element = current_hospital_elements[i] 

                try:
                    hospital_name_aria = hospital_element.get_attribute("aria-label")
                    hospital_name_text = hospital_element.inner_text().split("\n")[0].strip()
                    hospital_name = hospital_name_aria if hospital_name_aria and "Search result" not in hospital_name_aria else hospital_name_text
                    
                    if not hospital_name or "Search result" in hospital_name:
                        name_element = hospital_element.query_selector("div[class*='fontHeadlineSmall']")
                        if name_element:
                            hospital_name = name_element.inner_text().strip()
                        else:
                            hospital_name = f"Hospital Entry {i+1} (Name not fully resolved)"
                            
                    hospital_data["hospital_name"] = hospital_name
                    print(f"\nProcessing: {hospital_name}")

                    print(f"Clicking on hospital entry: {hospital_name}")
                    hospital_element.click()
                    
                    reviews_tab_selector = "button[aria-label*='Reviews for '], button:has-text('Reviews')"
                    page.wait_for_selector(reviews_tab_selector, timeout=30000)
                    print("Hospital details panel loaded.")
                    
                    reviews_tab = page.query_selector(reviews_tab_selector)
                    if reviews_tab:
                        reviews_tab.click()
                        print("Clicked 'Reviews' tab.")
                        review_entry_selector = "div[data-review-id]" 
                        page.wait_for_selector(review_entry_selector, timeout=30000)
                        print("Reviews initially loaded.")
                        time.sleep(3) # Allow initial reviews to render fully

                        # --- Improved Scrolling Logic for Reviews ---
                        scroll_panel = None
                        # Try specific selector first
                        specific_scroll_selector = f"div[role='main'] > div[tabindex]:has({review_entry_selector})"
                        print(f"Attempting to find scroll panel with specific selector: '{specific_scroll_selector}'")
                        scroll_panel = page.query_selector(specific_scroll_selector)

                        if not scroll_panel:
                            print("Specific scroll panel not found. Trying general overflow selectors.")
                            general_overflow_selectors = [
                                f"div[style*='overflow-y: scroll']:has({review_entry_selector})",
                                f"div[style*='overflow: scroll']:has({review_entry_selector})",
                                f"div[style*='overflow-y: auto']:has({review_entry_selector})",
                                f"div[style*='overflow: auto']:has({review_entry_selector})"
                            ]
                            for sel in general_overflow_selectors:
                                print(f"Trying general selector: '{sel}'")
                                scroll_panel = page.query_selector(sel)
                                if scroll_panel:
                                    print(f"Found scroll panel with general selector: '{sel}'")
                                    break
                        
                        if not scroll_panel:
                            print("General overflow scroll panels not found. Trying very general parent selector.")
                            very_general_selector = f"div:has({review_entry_selector})"
                            print(f"Trying very general selector: '{very_general_selector}'")
                            scroll_panel = page.query_selector(very_general_selector)
                            if scroll_panel:
                                print(f"Found scroll panel with very general selector: '{very_general_selector}' (use with caution).")


                        if scroll_panel:
                            print("Scroll panel identified. Attempting to scroll for more reviews...")
                            max_scroll_attempts = 5
                            scroll_delay_ms = 2500 
                            
                            reviews_query_selector_all = lambda: page.query_selector_all(review_entry_selector)
                            reviews_loaded_count_before_scroll = len(reviews_query_selector_all())
                            print(f"Reviews before scrolling: {reviews_loaded_count_before_scroll}")

                            for attempt in range(max_scroll_attempts):
                                print(f"Scroll attempt {attempt + 1}/{max_scroll_attempts}")
                                
                                try:
                                    last_scroll_height = scroll_panel.evaluate("el => el.scrollHeight")
                                    scroll_panel.evaluate("el => el.scrollTop = el.scrollHeight")
                                    page.wait_for_timeout(scroll_delay_ms) # Wait for content to load and animations
                                except Exception as e_scroll_eval:
                                    print(f"Error during scroll evaluation: {e_scroll_eval}. Panel might have disappeared.")
                                    break # Stop scrolling if panel is gone

                                current_reviews_elements = reviews_query_selector_all()
                                current_reviews_count = len(current_reviews_elements)
                                print(f"Reviews after scroll attempt {attempt + 1}: {current_reviews_count}")

                                new_scroll_height = scroll_panel.evaluate("el => el.scrollHeight") if scroll_panel.is_visible() else last_scroll_height

                                if current_reviews_count > reviews_loaded_count_before_scroll:
                                    print(f"More reviews loaded ({current_reviews_count - reviews_loaded_count_before_scroll} new). Continuing scroll.")
                                    reviews_loaded_count_before_scroll = current_reviews_count
                                elif new_scroll_height > last_scroll_height:
                                    print("Scroll height increased, more content might be available. Continuing scroll.")
                                    # Keep reviews_loaded_count_before_scroll the same to check if new *items* appear next
                                elif new_scroll_height == last_scroll_height and current_reviews_count == reviews_loaded_count_before_scroll:
                                     print("Scroll height and review count unchanged. Assuming end of reviews or no new ones loaded by this scroll.")
                                     break
                                else:
                                    print("No new review items loaded in this attempt, but scroll height might have changed or other activity. Continuing for now.")
                                
                                if attempt == max_scroll_attempts - 1:
                                    print("Max scroll attempts reached.")
                            print("Scrolling phase finished.")
                        else:
                            print("Could not identify a scrollable container for reviews. Scraping initially visible reviews only.")
                        # --- End of Improved Scrolling Logic ---

                        review_elements_playwright = page.query_selector_all(review_entry_selector) 
                        print(f"Found {len(review_elements_playwright)} review elements after scrolling attempts.")

                        for rev_idx, review_el_playwright in enumerate(review_elements_playwright):
                            if rev_idx >= MAX_REVIEWS_PER_HOSPITAL:
                                print(f"Reached MAX_REVIEWS_PER_HOSPITAL ({MAX_REVIEWS_PER_HOSPITAL}).")
                                break
                            try:
                                more_button = review_el_playwright.query_selector("button:has-text('More')")
                                if more_button and more_button.is_visible():
                                    try:
                                        print("Clicking 'More' button for a review...")
                                        more_button.click(timeout=3000) 
                                        time.sleep(0.7) 
                                    except Exception as e_more:
                                        print(f"Could not click 'More' button or it disappeared: {e_more}")
                                
                                review_html_content = review_el_playwright.evaluate("el => el.outerHTML")
                                soup = BeautifulSoup(review_html_content, 'html.parser')

                                author_tag = soup.select_one("div.d4r55, .WebRating-name") 
                                author_name = author_tag.get_text(strip=True) if author_tag else "N/A"

                                rating_tag = soup.select_one("span.kvMYJc[aria-label], span.WebRating-starValue[aria-label]")
                                rating = rating_tag['aria-label'] if rating_tag and rating_tag.has_attr('aria-label') else "N/A"
                                
                                text_tag = soup.select_one("span.wiI7pd, span.WebRating-description") 
                                review_text = text_tag.get_text(strip=True) if text_tag else ""
                                
                                date_tag = soup.select_one("span.rsqaWe, span.WebRating-date")
                                review_date = date_tag.get_text(strip=True) if date_tag else "N/A"

                                hospital_data["reviews"].append({
                                    "author": author_name, "rating": rating,
                                    "text": review_text, "date": review_date
                                })
                            except Exception as e_rev_parse:
                                print(f"Error parsing a review with BeautifulSoup: {e_rev_parse}")
                                hospital_data["reviews"].append({
                                    "author": "Error", "rating": "Error",
                                    "text": f"Could not parse review: {e_rev_parse}", "date": "Error"
                                })
                        
                        print(f"Scraped {len(hospital_data['reviews'])} reviews for {hospital_name}.")
                    else:
                        print(f"Could not find 'Reviews' tab for {hospital_name}.")
                
                except PlaywrightTimeoutError as t_err:
                    print(f"Timeout error processing {hospital_data.get('hospital_name', f'Hospital Entry {i+1}')}: {t_err}")
                except Exception as e:
                    print(f"General error processing {hospital_data.get('hospital_name', f'Hospital Entry {i+1}')}: {e}")
                
                finally:
                    all_hospitals_data.append(hospital_data)
                    print(f"Finished processing for: {hospital_data.get('hospital_name', 'N/A')}. Ensuring list context.")
                    if not page.query_selector(results_list_selector): 
                        print("Results list seems to be gone. Trying to go back.")
                        try:
                            page.go_back(wait_until="networkidle", timeout=10000)
                            time.sleep(3)
                            if not page.query_selector(results_list_selector):
                                print("Going back didn't restore results. Stopping.")
                                break 
                        except Exception as e_back:
                            print(f"Error going back: {e_back}. Stopping.")
                            break
                    else:
                        if page.query_selector(results_list_selector):
                           page.query_selector(results_list_selector).scroll_into_view_if_needed()
                           time.sleep(1) 

        except PlaywrightTimeoutError as e:
            print(f"A timeout occurred: {e}")
            print("Page might not have loaded or selectors are incorrect/changed.")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")
        finally:
            print("\n--- Scraping Complete ---")
            if browser: 
                browser.close()
            
    return all_hospitals_data

if __name__ == "__main__":
    print("Starting Google Maps hospital review scraper...")
    scraped_data = scrape_google_maps_reviews()

    if scraped_data:
        print("\n--- Scraped Data ---")
        print(json.dumps(scraped_data, indent=4, ensure_ascii=False))
        try:
            with open("hospital_reviews.json", "w", encoding="utf-8") as f:
                json.dump(scraped_data, f, indent=4, ensure_ascii=False)
            print("\nData saved to hospital_reviews_bs4_scrolled.json")
        except Exception as e:
            print(f"\nError saving data to file: {e}")
    else:
        print("No data was scraped.")

