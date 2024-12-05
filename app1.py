import json
import openai
import os
import datetime
import random
import pandas as pd
import re
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import stripe
from dotenv import load_dotenv
from pymongo import MongoClient
from bson.objectid import ObjectId

# Load environment variables
load_dotenv()

openai_api_key = os.getenv('OPENAI_API_KEY')
STRIPE_API_KEY = os.getenv('STRIPE_API_KEY')
MONGO_URI = os.getenv('MONGO_URI')  # Ensure you have set this environment variable

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.urandom(24)  # For session management

# Set OpenAI API key
openai.api_key = openai_api_key  # Ensure your API key is set in the environment variable
stripe.api_key  = STRIPE_API_KEY
client = MongoClient(MONGO_URI)
db = client['TIVOLI']

# Global variables to store menu data and recommendations
menu_data = {}
recommendations = []

def send_email(user_name, user_email, vendor_email, user_address, delivery_datetime, contact_number, menu_data):
    smtp_server = "smtp.gmail.com"
    smtp_port = 587
    sender_email = "SHREY@TRYDICE.COM"  # Replace with your email
    sender_password = "lwsg atsi oqys mhua"      # Replace with your email password
    subject = "Finalized Event Menu and Delivery Details"
    message = f"""\
    <html>
    <body>
        <h2>Order Confirmation for {user_name}</h2>
        <p><strong>Delivery Address:</strong> {user_address}</p>
        <p><strong>Delivery Date & Time:</strong> {delivery_datetime}</p>
        <p><strong>Contact Number:</strong> {contact_number}</p>
        <p><strong>Total Cost:</strong> ${menu_data['Total_Cost']}</p>
        <h3>Final Menu Details:</h3>
        <ul>
            {"".join([f"<li>{course}: {[f'{item['Item']} (Portion: {item['Selected Portion']['Qty']}, Quantity: {item['Quantity']})' for item in items]}</li>" for course, items in menu_data['Final Menu'].items()])}
        </ul>
    </body>
    </html>
    """

    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = f"{user_email}, {vendor_email}"
    msg['Subject'] = subject
    msg.attach(MIMEText(message, "html"))

    try:
        with smtplib.SMTP(smtp_server, smtp_port) as server:
            server.starttls()
            server.login(sender_email, sender_password)
            server.sendmail(sender_email, [user_email, vendor_email], msg.as_string())
        print("Email sent successfully!")
    except Exception as e:
        print(f"Error sending email: {e}")

def extract_event_details(user_input):
    """Extract event details from user input using OpenAI API, including main course preferences if specified."""
    logging.debug("Extracting event details from user input.")
    
    # Define possible main course options
    main_course_options = ["pizza", "sandwich", "grain", "pasta", "calzone"]
    
    prompt = f"""
    Extract the following information from the user's input:

    - **Budget** (numeric value)
    - **Headcount** (numeric value)
    - **Dietary restrictions** (if any) and the number of guests for each (e.g., 1 vegan, 2 gluten-free)
    - **Budget per person (Bpp)** by dividing total budget / total headcount
    - **Preferred main course** (if the user specifies one of these: pizza, sandwich, grain, pasta, calzone)

    **User Input:**
    "{user_input}"

    **Important Instructions:**
    - if there is no budget than put the budget as 18$ * headcount
    - User can also write gf for gluten-free or veg for vegeterian and other similar things.
    - user can also put like this for budget (not more than , not less than )
    - if user put budget in the range than take average of that range.
    - **Respond only with a valid JSON object** as specified below.
    - **Do not include any text, explanations, or comments** outside the JSON object.
    - The JSON should start at the **very first character** of your response.
    - If you cannot provide the requested output, respond with an empty JSON object.

    **Response Format (JSON Only):**
    {{
        "budget": value,
        "headcount": value,
        "restrictions": {{"restriction_name": number_of_guests, ...}},
        "Bpp": value,
        "preferred_main_course": "preferred course"  # optional, only if specified by user
    }}
    """
    
    try:
        response = openai.ChatCompletion.create(
            model='gpt-4o',  # or 'gpt-3.5-turbo'
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0,
            max_tokens=500,
        )
        response_text = response.choices[0].message.content.strip()
        logging.debug(f"LLM response: {response_text}")

        # Extract JSON from the response
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
            event_details = json.loads(json_str)
            logging.debug(f"Extracted event details: {event_details}")
        else:
            event_details = {}
            logging.warning("No JSON object found in LLM response.")

        # Proceed only if event_details is not empty
        if event_details:
            event_details['budget'] = float(event_details.get('budget', 0))
            event_details['headcount'] = int(event_details.get('headcount', 0))
            if 'Bpp' not in event_details or event_details['Bpp'] == 0:
                if event_details['headcount'] > 0:
                    event_details['Bpp'] = event_details['budget'] / event_details['headcount']
                else:
                    event_details['Bpp'] = 0
            event_details['restrictions'] = event_details.get('restrictions', {})

            # Check if there's a specified main course preference
            preferred_course = event_details.get('preferred_main_course')
            if preferred_course and preferred_course.lower() in main_course_options:
                event_details['preferred_main_course'] = preferred_course.lower()
            else:
                event_details['preferred_main_course'] = None  # No preference specified

            return event_details
        else:
            return None
    except Exception as e:
        logging.error(f"Error extracting event details: {e}")
        return None


def load_menu(main_course_file, others_file='Menu_Others.json'):
    """Load and organize menu items by course type from a main course file and an additional file for sides, appetizers, and desserts."""
    combined_menu = {'Main': [], 'Side': [], 'Appetizer': [], 'Dessert': []}

    # Load main course items from the specified main course file
    try:
        with open(main_course_file, 'r') as f:
            data = json.load(f)
            for item in data:
                if item.get('T') == 'Main':
                    combined_menu['Main'].append(item)
    except Exception as e:
        logging.error(f"Error loading main course data from {main_course_file}: {e}")

    # Load sides, appetizers, and desserts from the others file
    try:
        with open(others_file, 'r') as f:
            data = json.load(f)
            for item in data:
                item_type = item.get('T')
                if item_type in combined_menu:
                    combined_menu[item_type].append(item)
    except Exception as e:
        logging.error(f"Error loading other menu data from {others_file}: {e}")

    logging.debug(f"Loaded and combined menu data from {main_course_file} and {others_file}: {combined_menu}")
    return combined_menu

def build_prompt(event_details, course_type, menu_items, remaining_budget, budget_percentage, dish_limits):
    headcount = event_details['headcount']
    bpp = event_details['Bpp']

    special_instructions = """
    - Ensure each selected item includes 'Item', 'Selected Portion' (with 'Qty' and 'Cost'), 'Quantity', 'Total_Servings', and 'Total_Cost'.
    - 'Quantity' is the number of portions needed.
    - 'Total_Servings' is 'Quantity' * 'Qty' of the selected portion.
    - 'Total_Cost' is 'Quantity' * 'Cost' of the selected portion.
    - Include at least one vegetarian option.
    - Do not repeat dishes across different menus.
    - 'Quantity' must be a whole number (integer). Round up if necessary.
    - if you're give three menu for any particular main (for example pizza,pasta,etc) than make sure in all 3 menus mains should be different still you can put maximum 60 percent same items only. 

    **Menu Type Requirements:**
    - **Sandwich/wraps Menu:**
      - Should have 5-6 options for main items MANDATORY


    - **Calzones Menu:**
      - Should have 5-6 options for main items MANDATORY
      


    - **Salad/grain Menu:**
      - Should not have salad as a side MANDATORY 
      - Fresh Homemade Rolls and Butter are a mandatory side and it's free so always add it in **side** menu


    - **Mains/pasta Menu:**
      - Fresh Homemade Rolls and Butter are a mandatory  and it's free so always put it in menu in **side menu **
 
 

    - **Pizza Menu:**
      - Should have 5-7 options for main items MANDATORY
    



    """

    prompt = f"""
    You are an expert WITH 25 YEARS OF EXPERIENCE AS  caterer specializing in Italian cuisine WHOSE EXPERTISE ALIGN WITH POPRTIONING OF FOOD AND PROVIDE EVERYTHING IN THE BUDGET WITH EQUAVIVELENT FOOD QUANTITY ACCORDING TO HEADCOUNT.
    NEVER ADD MORE THAN 3 SIDES AND 2 APPETIZERS WHATEVER THE BUDGET IS. ALWAYS TRY TO ADD SIDES AND APPETIZERS FIRST. THIS IS YOUR CORE BELIEF

    **Important Instructions:**
    - ALWAYS ADD SIDES IN IT YOU CAN GO TO 0.5 OF HEADCOUNT FOR PORTION SIZE JUST SO YOU CAN ADD SIDES IN MENU
    - Respond **only** with a valid JSON object as specified below.
    - **Do not include any text, explanations, or comments outside the JSON object.**
    - The JSON should start at the **very first character** of your response.
    - If you cannot provide the requested output, respond with an empty JSON object.
    - ALWAYS PROVIDE VEG AND NON-VEG OPTIONS
    - ALWAYS KEEP PORTION = HEADCOUNT IN MAIN COURSE


    
    **Event Details:**
    Total Budget: {event_details['budget']}
    Remaining Budget: {remaining_budget}
    Budget Percentage Allowed: {budget_percentage}%
    Headcount: {headcount}
    Budget Per Person (BPP): ${bpp:.2f}
    Dietary Restrictions: {event_details.get('restrictions', 'None')}
    Cuisine Preferences: Italian

    **Available Menu Items:**
    Each item includes:
    - 'Item': The name of the dish
    - 'Portion Qty': Number of servings per portion
    - 'Cost': Cost per portion
    - 'Dietary Restrictions': Applicable dietary restrictions
    - 'Tags': Tags associated with the item
    - 'Category': The item type

    {json.dumps(menu_items, indent=2)}

    **Response Format (JSON Only):**
    {{
      "selected_items": [
        {{
          "Item": "Dish Name",
          "Selected Portion": {{
              "Qty": servings_per_portion,
              "Cost": cost_per_portion
          }},
          "Quantity": integer,
          "Total_Servings": integer,
          "Total_Cost": value
          "Dietary Restrictions": "dietary restrictions applicable to the dish"
        }}
      ],
      "course_total_cost": value
    }}

    **Additional Instructions:**
    {special_instructions}
    """
    return prompt

def parse_llm_response(response_text, remaining_budget):
    logging.debug("Parsing LLM response.")
    json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
    if json_match:
        json_str = json_match.group(0)
        try:
            data = json.loads(json_str)
            selected_items = data.get('selected_items', [])
            total_cost = data.get('course_total_cost', 0)
            if total_cost > remaining_budget:
                logging.warning("Total cost exceeds remaining budget.")
                return [], 0
            logging.debug(f"Selected items: {selected_items}")
            return selected_items, total_cost
        except json.JSONDecodeError as e:
            logging.error(f"JSON decoding error: {e}")
            return [], 0
    else:
        logging.warning("No JSON object found in LLM response.")
        return [], 0

def menu_agent(event_details, remaining_budget, budget_percentage, course_type, menu_data, dish_limit):
    logging.debug(f"Running menu agent for course type: {course_type}")
    menu_items = menu_data.get(course_type, [])
    if not menu_items:
        logging.warning(f"No menu items found for course type: {course_type}")
        return [], remaining_budget

    # Simplify menu items
    simplified_menu_items = []
    for item in menu_items:
        for portion in item.get('P', []):
            simplified_item = {
                "Item": item.get('I'),
                "Portion Qty": portion.get('Qty'),
                "Cost": portion.get('Cost'),
                "Dietary Restrictions": item.get('D'),
                "Tags": item.get('Tags'),
                "Category": item.get('T')
            }
            simplified_menu_items.append(simplified_item)

    dish_limits = {course_type: dish_limit}

    max_retries = 1
    for attempt in range(max_retries):
        logging.debug(f"Attempt {attempt + 1} for course type: {course_type}")
        prompt = build_prompt(event_details, course_type, simplified_menu_items, remaining_budget, budget_percentage, dish_limits)
        try:
            llm_response = openai.ChatCompletion.create(
                model='gpt-4o',
                messages=[{'role': 'user', 'content': prompt}],
                temperature=0,
                max_tokens=15000,
            )
            response_text = llm_response.choices[0].message.content.strip()
            logging.debug(f"LLM response: {response_text}")
            selected_items, total_cost = parse_llm_response(response_text, remaining_budget)
            if selected_items:
                remaining_budget -= total_cost
                logging.debug(f"Selected items for {course_type}: {selected_items}")
                logging.debug(f"Remaining budget: {remaining_budget}")
                return selected_items, remaining_budget
            else:
                logging.warning(f"No valid items selected for {course_type} on attempt {attempt + 1}")
                continue
        except Exception as e:
            logging.error(f"Error during LLM call: {e}")
            continue

    logging.error(f"Failed to select items for course type: {course_type} after {max_retries} attempts.")
    return [], remaining_budget

def generate_combined_menu():
    # List of available menu files
    menu_files = [
        'Menu_Calzones.json',
        'Menu_grain.json',
        'Menu_pasta.json',
        'Menu_pizza.json',
        'Menu_Sandwich.json'
    ]

    # Select 3 random menu files
    selected_files = random.sample(menu_files, 3)
    logging.info(f"Selected menu files: {selected_files}")

    # Load the selected files
    combined_menu = load_menu(selected_files)
    
    return combined_menu

def generate_recommendation(event_details, budget_multiplier, main_menu_data):
    logging.debug(f"Generating recommendation with budget multiplier: {budget_multiplier}")
    total_budget = event_details['budget'] * budget_multiplier
    remaining_budget = total_budget

    if total_budget / event_details['headcount'] < 0:
        logging.warning("Insufficient budget per person.")
        return None  # Insufficient budget

    budget_percentages = {
        'Main': 0,
        'Side': 0,
        'Appetizer': 0,
        'Dessert': 0
    }

    final_menu = {}

    # 1. Select Main Course
    selected_items, remaining_budget = menu_agent(
        event_details,
        remaining_budget,
        budget_percentages['Main'],
        'Main',
        main_menu_data,
        None
    )
    if not selected_items:
        logging.warning("Unable to select main course within the budget.")
        return None  # Unable to select main course within the budget
    final_menu['Main Course'] = selected_items

    # 2. Select Side Dishes
    for course_type in ['Side', 'Appetizer', 'Dessert']:
        if remaining_budget > 0:
            selected_items, remaining_budget = menu_agent(
                event_details,
                remaining_budget,
                budget_percentages[course_type],
                course_type,
                main_menu_data,
                2
            )
            if selected_items:
                final_menu[course_type] = selected_items

    total_cost = total_budget - remaining_budget
    logging.debug(f"Final menu generated with total cost: {total_cost}")
    return {
        'Final Menu': final_menu,
        'Total Cost': total_cost,
        'Remaining Budget': remaining_budget,
        'Budget Multiplier': budget_multiplier,
        'Headcount': event_details['headcount']
    }

# List of all main course menu file paths
menu_files = ['Menu_Calzones.json', 'Menu_grain.json', 'Menu_pasta.json', 'Menu_pizza.json', 'Menu_Sandwich.json']

# Load main course menu with random file selection
menu_data = load_menu(menu_files)

# Load side, appetizer, and dessert data from Menu_Others.json
with open('Menu_Others.json', 'r') as f:
    other_menu_data = json.load(f)


@app.route('/', methods=['GET', 'POST'])
def index():
    event_details_input = ''
    if request.method == 'POST':
        event_details_input = request.form['event_details']
        logging.debug(f"Received event details input: {event_details_input}")
        event_details = extract_event_details(event_details_input)
        if not event_details:
            error_message = "Unable to extract event details. Please check your input."
            logging.error(error_message)
            return render_template('index.html', error=error_message, event_details_input=event_details_input)
        session['event_details'] = event_details
        session['event_details_input'] = event_details_input

        # **Store the raw input and extracted details in the database**
        event_collection = db['event_details']
        event_doc = {
            'user_input': event_details_input,
            'extracted_details': event_details,
            'timestamp': datetime.datetime.utcnow()
        }
        event_id = event_collection.insert_one(event_doc).inserted_id

        # Store event_id in session for future reference
        session['event_id'] = str(event_id)

        # Determine which main course files to use
        main_menu_files = {
            "pizza": "Menu_pizza.json",
            "sandwich": "Menu_Sandwich.json",
            "grain": "Menu_grain.json",
            "pasta": "Menu_pasta.json",
            "calzone": "Menu_Calzones.json"
        }

        selected_files = []
        if event_details.get('preferred_main_course'):
            # Use the specified main course file three times if a preference is given
            selected_file = main_menu_files[event_details['preferred_main_course']]
            selected_files = [selected_file] * 3
        else:
            # Otherwise, select three unique files randomly
            selected_files = random.sample(list(main_menu_files.values()), 3)

        # Generate recommendations
        global recommendations
        recommendations = []
        budget_multipliers = [1,1.05,1.1]
        
        for i, file in enumerate(selected_files):
            main_menu_data = load_menu(file)  # Load main course data from the selected file
            rec = generate_recommendation(event_details, budget_multipliers[i], main_menu_data)
            if rec:
                recommendations.append(rec)
                logging.debug(f"Recommendation added: {rec}")
            else:
                logging.warning(f"No recommendation generated for multiplier {budget_multipliers[i]}")

        if not recommendations:
            error_message = "No valid recommendations could be generated based on the provided details."
            logging.error(error_message)
            return render_template('index.html', error=error_message)
        else:
            # **Store the generated recommendations in the database**
            recommendations_collection = db['recommendations']
            recommendations_docs = []
            for rec in recommendations:
                rec_doc = {
                    'event_id': session['event_id'],
                    'recommendation': rec,
                    'timestamp': datetime.datetime.utcnow()
                }
                recommendations_docs.append(rec_doc)
            # Insert all recommendations at once
            recommendations_collection.insert_many(recommendations_docs)

            session['recommendations'] = recommendations
            return redirect(url_for('show_recommendations'))
    else:
        event_details_input = request.args.get('event_details_input', '')

    return render_template('index.html')

@app.route('/recommendations', methods=['GET', 'POST'])
def show_recommendations():
    recommendations = session.get('recommendations', [])
    event_details_input = session.get('event_details_input', 'No details provided')  # Retrieve the raw input
    if not recommendations:
        logging.warning("No recommendations found in session.")
        return redirect(url_for('index'))

    if request.method == 'POST':
        selected_rec_index = int(request.form['selected_rec'])
        print(selected_rec_index)
        logging.debug(f"User selected recommendation index: {selected_rec_index}")
        session['selected_rec'] = recommendations[selected_rec_index]
        session['selected_rec_index'] = selected_rec_index

                # **Store the selected recommendation in the database**
        user_selection_collection = db['user_selections']
        selection_doc = {
            'event_id': session.get('event_id'),
            'selected_rec_index': selected_rec_index,
            'selected_recommendation':  recommendations[selected_rec_index],
            'timestamp': datetime.datetime.utcnow()
        }
        selection_id = user_selection_collection.insert_one(selection_doc).inserted_id

        # Store selection_id in session for future reference
        session['selection_id'] = str(selection_id)

        return redirect(url_for('chat'))

    return render_template('recommendations.html', recommendations=recommendations, event_details_input= event_details_input)

@app.route('/chat', methods=['GET', 'POST'])
def chat():
    selected_rec_index = session.get('selected_rec_index') 
    print(selected_rec_index) # Retrieve index from session
    selected_rec = session.get('selected_rec', None)
    print(selected_rec)
    if not selected_rec:
        return redirect(url_for('index'))

    if 'chat_history' not in session:
        session['chat_history'] = []

    if request.method == 'POST':
        user_input = request.form['user_input']
        session['chat_history'].append({'role': 'user', 'content': user_input})

        # **Store the user's message into the database**
        chat_collection = db['chat_sessions']
        chat_doc_user = {
            'event_id': session.get('event_id'),
            'selection_id': session.get('selection_id'),
            'message': user_input,
            'sender': 'user',
            'timestamp': datetime.datetime.utcnow()
        }
        chat_collection.insert_one(chat_doc_user)


        # Use LLM to interpret the user's query and respond accordingly
        action = interpret_user_query(user_input)
        assistant_response = handle_action(selected_rec, action, user_input)
        session['chat_history'].append({'role': 'assistant', 'content': assistant_response})

        # **Store the assistant's response into the database**
        chat_doc_assistant = {
            'event_id': session.get('event_id'),
            'selection_id': session.get('selection_id'),
            'message': assistant_response,
            'sender': 'assistant',
            'timestamp': datetime.datetime.utcnow()
        }
        chat_collection.insert_one(chat_doc_assistant)

        user_selection_collection = db['user_selections']
        selection_id = session.get('selection_id')
        if selection_id:
            # Update the selected recommendation in the database
            user_selection_collection.update_one(
                {'_id': ObjectId(selection_id)},
                {'$set': {'selected_recommendation': selected_rec}}
            )
        else:
            # Handle the case where selection_id is not in session
            logging.warning("Selection ID not found in session during chat.")
            return redirect(url_for('index'))

        # Update the session with the modified recommendation and index
        session['selected_rec'] = selected_rec  # Store the modified recommendation
        session['selected_rec_index'] = selected_rec_index  # Ensure the index is saved for /final_menu
        print(selected_rec_index)
        if action.get('action') == 'finalize_menu':
            return redirect(url_for('final_menu'))

    return render_template('chat.html', chat_history=session['chat_history'], selected_rec=selected_rec)

@app.route('/checkout', methods=['POST'])
def checkout():
    print("Checkout form data:", request.form)  # Debug: Print form data

    # Collect user details from the form
    user_name = request.form.get('user_name')
    user_email = request.form.get('user_email')
    user_address = request.form.get('user_address')
    delivery_datetime = request.form.get('delivery_datetime')
    contact_number = request.form.get('contact_number')
    
    # Retrieve the selected_rec_index from the form
    selected_rec_index = request.form.get('selected_rec')
    print("Selected Recommendation Index in Checkout:", selected_rec_index)  # Debug: Check selected_rec value

    if selected_rec_index is None:
        print("Error: selected_rec_index is None.")
        return "No menu selected. Please try again.", 400

    try:
        selected_rec_index = int(selected_rec_index)
    except ValueError:
        print(f"Error: selected_rec_index is invalid. Value received: {selected_rec_index}")
        return "Invalid selection. Please try again.", 400

    # Retrieve the selected recommendation from the session
    recommendations = session.get('recommendations', [])
    if not recommendations or selected_rec_index >= len(recommendations):
        print("Error: No valid recommendation found for the selected index.")
        return "No menu selected", 400

    selected_rec = recommendations[selected_rec_index]
    
    # Recalculate totals to ensure we have the latest total cost after customization
    recalculate_totals(selected_rec)

    # Store user details and selected recommendation in the session for later use in the success route
    session['user_name'] = user_name
    session['user_email'] = user_email
    session['user_address'] = user_address
    session['delivery_datetime'] = delivery_datetime
    session['contact_number'] = contact_number
    session['selected_rec'] = selected_rec  # Store selected recommendation in session

    # **Store order details in the database**
    orders_collection = db['orders']
    user_details = {
        'user_name': user_name,
        'user_email': user_email,
        'user_address': user_address,
        'delivery_datetime': delivery_datetime,
        'contact_number': contact_number,
        'event_id': session.get('event_id'),
        'selection_id': session.get('selection_id'),
        'timestamp': datetime.datetime.utcnow()
    }
    order_doc = {
        'user_details': user_details,
        'selected_recommendation': selected_rec,
        'payment_status': 'pending',
        'timestamp': datetime.datetime.utcnow()
    }
    order_id = orders_collection.insert_one(order_doc).inserted_id
    # Store order_id in session
    session['order_id'] = str(order_id)

    # Calculate total amount in cents for Stripe (assuming selected_rec['Total_Cost'] is in dollars)
    total_amount = int(selected_rec['Total_Cost'] * 100)  # Convert to cents for Stripe
    print(f"Updated Total Amount for Stripe (cents): {total_amount}")

    try:
        # Create Stripe Checkout Session
        stripe_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': 'Customized Menu Recommendation',
                    },
                    'unit_amount': total_amount,
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=url_for('success', _external=True),
            cancel_url=url_for('cancel', _external=True),
            customer_email=user_email,
            metadata={
                'order_id': str(order_id),
                'user_name': user_name,
                'user_address': user_address,
                'delivery_datetime': delivery_datetime,
                'contact_number': contact_number,
                'selected_rec_index': selected_rec_index
            }
        )
        return redirect(stripe_session.url, code=303)
    except Exception as e:
        print(f"Stripe Checkout error: {e}")
        return jsonify(error=str(e)), 500



@app.route('/success')
def success():
    # Retrieve user details and selected recommendation from the session
    user_name = session.get('user_name')
    user_email = session.get('user_email')
    user_address = session.get('user_address')
    delivery_datetime = session.get('delivery_datetime')
    contact_number = session.get('contact_number')
    selected_rec = session.get('selected_rec')
    vendor_email = "Shrey@trydice.com"  # Replace with the actual vendor email

    # **Update the order's payment status to 'completed'**
    orders_collection = db['orders']
    order_id = session.get('order_id')
    if order_id:
        try:
            orders_collection.update_one(
                {'_id': ObjectId(order_id)},
                {'$set': {'payment_status': 'completed'}}
            )
        except Exception as e:
            print(f"Error updating payment status in database: {e}")
    else:
        print("Error: No order_id found in session.")

    # Check if all necessary details are available
    if user_name and user_email and selected_rec:
        try:
            # Call the send_email function to send the email
            send_email(
                user_name=user_name,
                user_email=user_email,
                vendor_email=vendor_email,
                user_address=user_address,
                delivery_datetime=delivery_datetime,
                contact_number=contact_number,
                menu_data=selected_rec
            )
            print("Email sent successfully!")
        except Exception as e:
            print(f"Error sending email: {e}")
    else:
        print("Missing user information or selected recommendation. Email not sent.")

    # Render the success page
    return render_template('success.html')

@app.route('/cancel')
def cancel():
    return render_template('cancel.html')



@app.route('/create-checkout-session', methods=['POST'])
def create_checkout_session():
    try:
        # Retrieve data from the request
        data = request.get_json()
        
        # Fetch the customized selected recommendation from the session
        selected_rec = session.get('selected_rec', None)
        if not selected_rec:
            print("Error: No valid customized recommendation found in session.")
            return jsonify({'error': 'No valid menu selected. Please try again.'}), 400

        # Recalculate totals to ensure we have the latest total cost after customization
        recalculate_totals(selected_rec)
        
        # Calculate total amount in cents for Stripe (assuming selected_rec['Total_Cost'] is in dollars)
        total_amount = int(selected_rec['Total_Cost'] * 100)  # Convert to cents for Stripe
        print(f"Calculated Total Amount (cents): {total_amount}")  # Debug print

        # **Collect user details from 'data' or session**
        user_name = data.get('user_name') or session.get('user_name')
        user_email = data.get('user_email') or session.get('user_email')
        user_address = data.get('user_address') or session.get('user_address')
        delivery_datetime = data.get('delivery_datetime') or session.get('delivery_datetime')
        contact_number = data.get('contact_number') or session.get('contact_number')

        if not all([user_name, user_email, user_address, delivery_datetime, contact_number]):
            print("Error: Missing user information.")
            return jsonify({'error': 'Missing user information. Please provide all required details.'}), 400

        # **Store order details in the database**
        orders_collection = db['orders']
        user_details = {
            'user_name': user_name,
            'user_email': user_email,
            'user_address': user_address,
            'delivery_datetime': delivery_datetime,
            'contact_number': contact_number,
            'event_id': session.get('event_id'),
            'selection_id': session.get('selection_id'),
            'timestamp': datetime.datetime.utcnow()
        }
        order_doc = {
            'user_details': user_details,
            'selected_recommendation': selected_rec,
            'payment_status': 'pending',
            'timestamp': datetime.datetime.utcnow()
        }
        order_id = orders_collection.insert_one(order_doc).inserted_id
        # Store order_id in session
        session['order_id'] = str(order_id)

        # Create a new Stripe Checkout Session with the dynamic order amount
        stripe_session = stripe.checkout.Session.create(
            payment_method_types=['card'],
            line_items=[{
                'price_data': {
                    'currency': 'usd',
                    'product_data': {
                        'name': 'Customized Menu Recommendation',
                    },
                    'unit_amount': total_amount,
                },
                'quantity': 1,
            }],
            mode='payment',
            success_url=url_for('success', _external=True) + '?session_id={CHECKOUT_SESSION_ID}',
            cancel_url=url_for('cancel', _external=True),
            customer_email=user_email,  # Optional: pre-fill the email if available
            metadata={
                'order_id': str(order_id),
                'user_name': user_name,
                'user_address': user_address,
                'delivery_datetime': delivery_datetime,
                'contact_number': contact_number
            }
        )
        return jsonify({'id': stripe_session.id})
    except Exception as e:
        print(f"Error creating Stripe session: {e}")
        return jsonify({'error': str(e)}), 500

# @app.route('/update-quantity', methods=['POST'])
# def update_quantity():
#     """Updates the quantity of an item in the selected menu."""
#     try:
#         data = request.get_json()
#         item_id = data['item_id']  # The unique identifier for the menu item
#         new_qty = int(data['new_qty'])  # The new quantity to update
        
#         # Retrieve the selected recommendation from the session
#         selected_rec = session.get('selected_rec', None)
#         if not selected_rec:
#             return jsonify({'success': False, 'message': 'No selected recommendation found.'}), 400

#         item_updated = False
#         # Update the quantity in the selected recommendation
#         for course_type, items in selected_rec['Final Menu'].items():
#             for item in items:
#                 if item['Item'] == item_id:  # Match based on item name or ID
#                     item['Quantity'] = new_qty
#                     item['Total_Servings'] = item['Selected Portion']['Qty'] * new_qty
#                     item['Total_Cost'] = item['Selected Portion']['Cost'] * new_qty
#                     item_updated = True
#                     updated_item = item
#                     break
#             if item_updated:
#                 break  # Exit the loop once the item is updated

#         if not item_updated:
#             return jsonify({'success': False, 'message': 'Item not found in the selected menu.'}), 404

#         # Recalculate totals
#         recalculate_totals(selected_rec)

#         # Update session with the modified recommendation
#         session['selected_rec'] = selected_rec
#         session.modified = True

#         return jsonify({
#             'success': True,
#             'message': 'Quantity updated successfully!',
#             'updated_item': {
#                 'Total_Servings': updated_item['Total_Servings'],
#                 'Total_Cost': updated_item['Total_Cost']
#             },
#             'total_cost': selected_rec['Total Cost']
#         })
#     except Exception as e:
#         logging.error(f"Error updating quantity: {e}")
#         return jsonify({'success': False, 'message': 'Failed to update quantity.'}), 500


@app.route('/update-quantity', methods=['POST'])
def update_quantity():
    data = request.get_json()
    item_id = data.get('item_id')
    new_qty = data.get('new_qty')

    selected_rec = session.get('selected_rec', None)
    if not selected_rec:
        return jsonify({'success': False, 'error': 'No selected menu found.'}), 400

    # Find the item in the Final Menu
    item_found = None
    category_found = None
    for category, items in selected_rec['Final Menu'].items():
        for item in items:
            if item['Item'] == item_id:
                item_found = item
                category_found = category
                break
        if item_found:
            break

    if not item_found:
        return jsonify({'success': False, 'error': 'Item not found in your menu.'}), 404

    # Update the quantity, total servings, and total cost
    item_found['Quantity'] = new_qty
    item_found['Total_Servings'] = new_qty * item_found['Selected Portion']['Qty']
    item_found['Total_Cost'] = new_qty * item_found['Selected Portion']['Cost']

    # Recalculate totals
    recalculate_totals(selected_rec)

    # Update session
    session['selected_rec'] = selected_rec

    return jsonify({
        'success': True,
        'updated_item': item_found,
        'total_cost': selected_rec.get('Total_Cost', 0.0)
    }), 200



@app.route('/final_menu')
def final_menu():
    selected_rec_index = session.get('selected_rec_index')
    recommendations = session.get('recommendations', [])

    if selected_rec_index is None or selected_rec_index >= len(recommendations):
        print(selected_rec_index)
        # Redirect if there's an issue with the selected index
        return redirect(url_for('index'))

    #selected_rec = recommendations[selected_rec_index]
    selected_rec = session.get('selected_rec', None)
    session['selected_rec'] = selected_rec  # Store for checkout
    recalculate_totals(selected_rec)
    return render_template('final_menu.html', selected_rec=selected_rec, recommendation_index=selected_rec_index)

def handle_action(selected_rec, action, user_input):
    """Handles the action determined by the LLM and returns a response."""
    logging.debug(f"Handling action: {action}")
    if action['action'] == 'add_item':
        return add_item_to_menu(selected_rec, menu_data, action)
    elif action['action'] == 'remove_item':
        return remove_item_from_menu(selected_rec, menu_data, action)
    elif action['action'] == 'ask_question':
        answer = answer_menu_question(menu_data, user_input)
        return answer
    elif action['action'] == 'finalize_menu':
        return "Your menu has been finalized."
    else:
        return "I'm sorry, I didn't understand that. Could you please rephrase?"

def interpret_user_query(user_input):
    """Uses LLM to interpret user's intent and determine action."""
    logging.debug("Interpreting user query.")
    prompt = f"""
    You are an assistant and also junior chef that interprets user commands and outputs a JSON object specifying the action to take.
    - if user says can we add dessert or appetizer or side ? it means that this is question but if it says cnan we add item_name than it is 'ADD' action.
    - and user ask for some item to add but it is not there than add nearest item but never say item not found 

    Possible actions:
    - select_recommendation (user wants to select one of the recommendations)
    - add_item (user wants to add an item to the menu)
    - remove_item (user wants to remove an item from the menu)
    - ask_question (user has a question about the menu)
    - finalize_menu (user wants to finalize the menu)

    For 'select_recommendation', provide 'recommendation_number' (integer).
    For 'add_item' or 'remove_item', provide only 'item_name' (string) without specifying 'course_type'.

    User Input:
    "{user_input}"

    Respond only with a JSON object in the following format:
    {{
      "action": "action_name",
      "recommendation_number": integer (if applicable),
      "item_name": "item name" (if applicable)
    }}
    """
    try:
        response = openai.ChatCompletion.create(
            model='gpt-4o',
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0,
            max_tokens=1500,
        )
        response_text = response.choices[0].message.content.strip()
        logging.debug(f"LLM response for query interpretation: {response_text}")

        # Extract JSON from the response
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            json_str = json_match.group(0)
            action = json.loads(json_str)
            return action
        else:
            logging.warning("No JSON object found in LLM response for query interpretation.")
            return {"action": "unknown"}
    except Exception as e:
        logging.error(f"Error interpreting user query: {e}")
        return {"action": "unknown"}

def add_item_to_menu(selected_rec, menu_data, action):
    """Adds an item to the selected menu using LLM for dynamic matching."""
    logging.debug("Adding item to menu using LLM for dynamic matching.")
    user_input = action.get('item_name')
    if not user_input:
        logging.warning("No item name provided in action.")
        return "No item name provided."

    # Extract all available menu item names across all categories
    menu_items = []
    for category, items in menu_data.items():
        for item in items:
            menu_items.append(item['I'])  # Assuming 'I' is the key for item name

    # Use LLM to find the best match
    matched_item_name = find_best_match(user_input, menu_items)

    if not matched_item_name:
        logging.warning(f"No matching item found for user input: {user_input}")
        return f"No matching item found for '{user_input}'. Please check the item name and try again."

    # Find the category and item details for the matched item
    matched_item = None
    matched_category = None
    for category, items in menu_data.items():
        for item in items:
            if item['I'].lower() == matched_item_name.lower():
                matched_item = item
                matched_category = category
                break
        if matched_item:
            break

    if not matched_item or not matched_category:
        logging.error(f"Matched item '{matched_item_name}' not found in menu data.")
        return f"Error finding the item '{matched_item_name}' in the menu. Please try again."

    # Proceed to add the matched item to the selected recommendation
    portions = matched_item.get('P', [])
    headcount = selected_rec.get('Headcount', 1)
    selected_portion = min(portions, key=lambda p: abs(p['Qty'] - headcount))
    portion_qty = selected_portion['Qty']
    cost_per_portion = selected_portion['Cost']

    # Calculate quantity needed to meet headcount
    quantity = -(-headcount // portion_qty)  # Ceiling division

    # Calculate total servings and total cost
    total_servings = quantity * portion_qty
    total_cost = quantity * cost_per_portion

    # Create item with all fields
    item_to_add = {
        'Item': matched_item['I'],
        'Selected Portion': {
            'Qty': portion_qty,
            'Cost': cost_per_portion
        },
        'Quantity': quantity,
        'Total_Servings': total_servings,
        'Total_Cost': total_cost,
        'Dietary Restrictions': matched_item.get('D', ''),
        'Tags': matched_item.get('Tags', []),
        'Category': matched_item.get('T', '')
    }

    # Add item to the selected recommendation
    if matched_category not in selected_rec['Final Menu']:
        selected_rec['Final Menu'][matched_category] = []
    selected_rec['Final Menu'][matched_category].append(item_to_add)

    # Recalculate totals after adding the item
    recalculate_totals(selected_rec)

    logging.debug(f"Item added to menu: {item_to_add}")
    return f"Added '{matched_item_name}' to '{matched_category}'."

def remove_item_from_menu(selected_rec, menu_data, action):
    """Removes an item from the selected menu using LLM for dynamic matching."""
    logging.debug("Removing item from menu using LLM for dynamic matching.")
    user_input = action.get('item_name')
    if not user_input:
        logging.warning("No item name provided in action.")
        return "No item name provided."

    # Extract all available menu item names across all categories in the selected menu
    menu_items = []
    for category, items in selected_rec['Final Menu'].items():
        for item in items:
            menu_items.append(item['Item'])  # Assuming 'Item' is the key for item name

    if not menu_items:
        logging.warning("No items available in the current menu to remove.")
        return "Your menu is currently empty. There's nothing to remove."

    # Use LLM to find the best match
    matched_item_name = find_best_match(user_input, menu_items)

    if not matched_item_name:
        logging.warning(f"No matching item found for user input: {user_input}")
        return f"No matching item found for '{user_input}'. Please check the item name and try again."

    # Find the category and item details for the matched item
    matched_item = None
    matched_category = None
    for category, items in selected_rec['Final Menu'].items():
        for item in items:
            if item['Item'].lower() == matched_item_name.lower():
                matched_item = item
                matched_category = category
                break
        if matched_item:
            break

    if not matched_item or not matched_category:
        logging.error(f"Matched item '{matched_item_name}' not found in selected menu.")
        return f"Error finding the item '{matched_item_name}' in your menu. Please try again."

    # Proceed to remove the matched item from the selected recommendation
    try:
        selected_rec['Final Menu'][matched_category].remove(matched_item)
        # If the category has no more items, optionally remove the category
        if not selected_rec['Final Menu'][matched_category]:
            del selected_rec['Final Menu'][matched_category]
    except ValueError:
        logging.error(f"Item '{matched_item_name}' could not be removed from category '{matched_category}'.")
        return f"Error removing the item '{matched_item_name}' from '{matched_category}'. Please try again."

    # Recalculate totals after removing the item
    recalculate_totals(selected_rec)

    logging.debug(f"Item removed from menu: {matched_item_name}")
    return f"Removed '{matched_item_name}' from '{matched_category}'."

def answer_menu_question(menu_data, user_question):
    """Answers questions about the menu using the menu data without requiring course type input."""
    logging.debug("Answering menu question.")
    menu_context = ""
    for category, items in menu_data.items():
        menu_context += f"\n{category}:\n"
        for item in items:
            menu_context += f"- {item['I']}: {item.get('D', 'No description available.')}\n"

    prompt = f"""
    You are a helpful assistant knowledgeable about the following menu:

    {menu_data}

    Answer the following question:

    {user_question}

    Provide a clear and concise answer.and always provide maximum 3 items wwith price.
    """
    try:
        response = openai.ChatCompletion.create(
            model='gpt-4o',
            messages=[{'role': 'user', 'content': prompt}],
            temperature=0.7,
            max_tokens=2000,
        )
        answer = response.choices[0].message.content.strip()
        logging.debug(f"Answer to menu question: {answer}")
        return answer
    except Exception as e:
        logging.error(f"Error answering menu question: {e}")
        return "I'm sorry, I couldn't find the information you're asking for."

def update_session(selected_rec):
    """Update selected_rec in the session with new values."""
    session['selected_rec'] = selected_rec
    session.modified = True  # Explicitly mark the session as modified

def recalculate_totals(selected_rec):
    """Recalculate Total Cost and Remaining Budget based on Final Menu items."""
    total_cost = 0
    for course_type, items in selected_rec['Final Menu'].items():
        for item in items:
            total_cost += item['Total_Cost']
    
    # Check if Budget is available, otherwise infer it from Remaining Budget and Total Cost
    if 'Budget' in selected_rec:
        initial_budget = selected_rec['Budget']
    else:
        # Fallback calculation in case Budget key is missing
        initial_budget = selected_rec.get('Remaining Budget', 0) + selected_rec.get('Total_Cost', 0)
    
    # Update selected_rec with recalculated totals
    selected_rec['Total_Cost'] = total_cost
    selected_rec['Remaining Budget'] = initial_budget - total_cost
    update_session(selected_rec)  # Update session after recalculation

#############################################
def find_best_match(user_input, menu_items):
    """
    Uses OpenAI's LLM to find the best matching menu item based on user input.

    Parameters:
        user_input (str): The item name input by the user.
        menu_items (list): A list of available menu item names.

    Returns:
        str: The matched menu item name or None if no suitable match is found.
    """
    prompt = f"""
    You are an intelligent assistant that helps match user input to available menu items.

    Available Menu Items:
    {', '.join(menu_items)}

    User Input:
    "{user_input}"

    Your task is to:
    1. Identify the menu item that best matches the user input.keep dietary restrictions and course item in mind IT IS MORE IMP.
    2. If the user input closely resembles a menu item (even with typos), return that item.
    3. If no close match is found, respond with "No match found".

    Respond only with the exact name of the matched menu item as it appears in the list. If no match is found, respond with "No match found".

    Example:
    - User Input: "peperoni piza"
    - Response: "Pepperoni Pizza"

    - User Input: "unknown item"
    - Response: "No match found"
    """

    try:
        response = openai.ChatCompletion.create(
            model='gpt-4o',
            messages=[
                {'role': 'system', 'content': 'You are a helpful assistant for matching menu items.'},
                {'role': 'user', 'content': prompt}
            ],
            temperature=0.3,
            max_tokens=60,
            n=1,
            stop=None
        )
        answer = response.choices[0].message.content.strip()
        if answer.lower() == "no match found":
            return None
        # Ensure the response matches one of the menu items
        if answer in menu_items:
            return answer
        else:
            return None
    except openai.error.Timeout:
        logging.error("OpenAI request timed out.")
        return None
    except openai.error.APIError as e:
        logging.error(f"OpenAI API error: {e}")
        return None
    except Exception as e:
        logging.error(f"Unexpected error in find_best_match: {e}")
        return None
############################################

@app.route('/get_total_cost', methods=['GET'])
def get_total_cost():
    """
    Returns the current total cost of the selected menu.
    """
    selected_rec = session.get('selected_rec', None)
    if not selected_rec:
        return jsonify({'error': 'No selected menu found.'}), 400

    total_cost = selected_rec.get('Total_Cost', 0.0)
    return jsonify({'total_cost': total_cost})

#############################################################


# ##############################################



if __name__ == '__main__':
    logging.info("Starting the Flask app.")
    app.run(debug=True)
