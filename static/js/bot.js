
document.addEventListener("DOMContentLoaded", function () {
    const MAX_MESSAGES = 3; // Maximum number of messages to display
    const REFRESH_TIME = 50000; // 50 seconds (in milliseconds)
    const END_CONVERSATION_KEYWORDS = ["ok", "ok great", "done", "thank you", "great"]; // Keywords for ending chat
    let refreshTimer = null; // Timer reference

///////////////////////////////////////////////

    // Handle Quantity Adjustment
    document.querySelectorAll('.quantity-btn').forEach(function (button) {
        button.addEventListener('click', function (event) {
            event.preventDefault();
            const row = this.closest('tr');
            const itemId = row.getAttribute('data-item-id');
            const quantityElement = row.querySelector('.item-quantity');
            let currentQuantity = parseInt(quantityElement.textContent);

            if (this.classList.contains('increase')) {
                currentQuantity += 1;
            } else if (this.classList.contains('decrease')) {
                if (currentQuantity > 1) { // Prevent quantity less than 1
                    currentQuantity -= 1;
                } else {
                    alert('Quantity cannot be less than 1.');
                    return;
                }
            }

            // Send AJAX request to update quantity
            fetch('/update-quantity', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': '{{ csrf_token() }}' // Include CSRF token if using Flask-WTF
                },
                body: JSON.stringify({
                    item_id: itemId,
                    new_qty: currentQuantity
                })
            })
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    // Update quantity and total cost on the page
                    quantityElement.textContent = currentQuantity;
                    // Optionally, update total servings and total cost for the item
                    row.querySelector('td:nth-child(4)').textContent = data.updated_item.Total_Servings;
                    row.querySelector('td:nth-child(5)').textContent = '$' + data.updated_item.Total_Cost.toFixed(2);
                    // Update total cost
                    // Update total cost
                    document.getElementById("total-cost").innerText = `Total Cost: $${data.total_cost.toFixed(2)}`;

                } else {
                    alert('Failed to update quantity.');
                }
            })
            .catch(error => {
                console.error('Error updating quantity:', error);
            });
        });
    });

///////////////////////////////////////////////////////////


    // Clear stored chat history on refresh or reload
    sessionStorage.clear();

    // Send Message Handler
    async function sendMessage(event) {
        event.preventDefault(); // Prevent form submission
        const userInput = document.getElementById('chat-input').value.trim().toLowerCase();

        if (userInput) {
            appendMessage('user', userInput); // Add user's message to chat
            document.getElementById('chat-input').value = ''; // Clear the input field

            // Check for end conversation keywords
            if (END_CONVERSATION_KEYWORDS.includes(userInput)) {
                openEmailModal(); // Trigger the checkout form modal
                return;
            }

            try {
                await fetchChatResponse(userInput); // Fetch response from the server
                window.location.reload(); // Reload the page to show the updated state
            } catch (error) {
                console.error('Error fetching chat response:', error);
                appendMessage('assistant', 'The assistant is currently unavailable. Please try again later.');
                window.location.reload(); // Reload the page in case of errors
            }
        }
    }

    // Append Message to Chat History
    function appendMessage(role, message) {
        const chatHistory = document.getElementById('chat-history');
        const bubble = document.createElement('div');
        bubble.classList.add('chat-bubble', role);

        const avatar = document.createElement('img');
        avatar.classList.add('avatar');
        avatar.src = role === 'user' ? '../static/assests/human.jpg' : '../static/assests/bot.png';
        avatar.alt = role === 'user' ? 'User' : 'Assistant';

        const text = document.createElement('p');
        text.innerHTML = `<strong>${role === 'user' ? 'You' : 'Assistant'}:</strong> ${message}`;

        bubble.appendChild(avatar);
        bubble.appendChild(text);
        chatHistory.appendChild(bubble);

        limitMessages(); // Limit the number of messages displayed
        chatHistory.scrollTop = chatHistory.scrollHeight; // Auto-scroll to the latest message
    }

    // Limit the Number of Messages in Chat History
    function limitMessages() {
        const chatHistory = document.getElementById('chat-history');
        const bubbles = chatHistory.getElementsByClassName('chat-bubble');
        if (bubbles.length > MAX_MESSAGES * 2) { // Each user input generates two bubbles (user + assistant)
            chatHistory.removeChild(bubbles[0]); // Remove the oldest bubble
        }
    }

    // Fetch Response from the Backend
    async function fetchChatResponse(message) {
        appendMessage('assistant', '<em>Typing...</em>'); // Add typing indicator

        try {
            const response = await fetch('/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: `user_input=${encodeURIComponent(message)}`, // URL-encoded data
            });

            // Remove the "Typing..." placeholder
            const chatHistory = document.getElementById('chat-history');
            chatHistory.lastChild.remove();

            if (response.ok) {
                const data = await response.json();
                if (data && data.response) {
                    appendMessage('assistant', data.response); // Show assistant's response
                } else {
                    appendMessage('assistant', "I'm sorry, I couldn't understand your request. Please try again.");
                }
            } else {
                console.error('Error in response:', response.status, response.statusText);
                appendMessage('assistant', "An error occurred while processing your request. Please try again.");
            }
        } catch (error) {
            console.error('Fetch error:', error);

            const chatHistory = document.getElementById('chat-history');
            if (chatHistory.lastChild.innerHTML.includes('<em>Typing...</em>')) {
                chatHistory.lastChild.remove();
            }

            appendMessage('assistant', 'The assistant is currently unavailable. Please try again later.');
        }
    }

    // Clear Chat History
    function clearChatHistory() {
        const chatHistory = document.getElementById('chat-history');
        chatHistory.innerHTML = ''; // Clear the chat history
        sessionStorage.clear(); // Clear sessionStorage to prevent reloading old chat
    }

    // Handle Page Visibility Changes
    function handleVisibilityChange() {
        if (document.hidden) {
            // Start a timer to clear the chat if the user switches tabs or navigates away
            refreshTimer = setTimeout(() => {
                clearChatHistory();
                console.log('Chat history cleared due to inactivity.');
            }, REFRESH_TIME);
        } else {
            // Cancel the timer if the user returns within 1 minute
            clearTimeout(refreshTimer);
            refreshTimer = null;
        }
    }

    // Open Modal for Checkout
    function openEmailModal() {
        const emailModal = document.getElementById('emailModal');
        emailModal.style.display = 'block';
    }

    // Close Modal for Checkout
    function closeEmailModal() {
        const emailModal = document.getElementById('emailModal');
        emailModal.style.display = 'none';
    }

    // Attach Event Listener to Form
    const form = document.querySelector('.chat-input-container');
    form.addEventListener('submit', sendMessage);

    // Monitor Page Visibility
    document.addEventListener('visibilitychange', handleVisibilityChange);

    // Handle Checkout Form Submission and Redirect to Stripe
    const emailForm = document.getElementById('emailForm');
    emailForm.addEventListener('submit', function (event) {
        event.preventDefault();

        const formData = new FormData(emailForm);
        const data = {
            user_name: formData.get('user_name'),
            user_email: formData.get('user_email'),
            user_address: formData.get('user_address'),
            delivery_datetime: formData.get('delivery_datetime'),
            contact_number: formData.get('contact_number'),
            selected_rec_index: "{{ recommendation_index }}"
        };

        fetch('/create-checkout-session', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(data),
        })
        .then(response => response.json())
        .then(session => {
            if (session && session.id) {
                const stripe = Stripe('pk_test_Ujwxvk3zBxt8yokfEFa8wSnX'); // Replace with your actual public key
                stripe.redirectToCheckout({ sessionId: session.id });
            } else {
                alert("Failed to initiate Stripe Checkout: No session ID.");
            }
        })
        .catch(error => {
            console.error("Error initiating Stripe checkout:", error);
            alert("Error initiating Stripe checkout.");
        });
    });

    // Close Modal on Outside Click
    window.onclick = function (event) {
        const emailModal = document.getElementById('emailModal');
        if (event.target == emailModal) {
            closeEmailModal();
        }
    };
});
    const stripe = Stripe('pk_test_Ujwxvk3zBxt8yokfEFa8wSnX'); // Replace with your actual public key

    // Open and Close Checkout Modal Functions
    function openEmailModal() {
        document.getElementById("emailModal").style.display = "block";
    }

    function closeEmailModal() {
        document.getElementById("emailModal").style.display = "none";
    }

    // Handle Form Submission and Redirect to Stripe
    document.getElementById("emailForm").addEventListener("submit", function(event) {
        event.preventDefault();

        const formData = new FormData(document.getElementById("emailForm"));
        const data = {
            user_name: formData.get("user_name"),
            user_email: formData.get("user_email"),
            user_address: formData.get("user_address"),
            delivery_datetime: formData.get("delivery_datetime"),
            contact_number: formData.get("contact_number"),
            selected_rec_index: formData.get("selected_rec_index")
        };

        fetch("/create-checkout-session", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(data)
        })
        .then(response => response.json())
        .then(session => {
            if (session && session.id) {
                stripe.redirectToCheckout({ sessionId: session.id });
            } else {
                alert("Failed to initiate Stripe Checkout: No session ID.");
            }
        })
        .catch(error => {
            console.error("Error initiating Stripe checkout:", error);
            alert("Error initiating Stripe checkout.");
        });
    });

    // Close modal on outside click
    window.onclick = function(event) {
        const modal = document.getElementById("emailModal");
        if (event.target == modal) {
            closeEmailModal();
        }
    };

    // Function to update total cost
    function updateTotalCost() {
        fetch("/get_total_cost", {
            method: "GET",
            headers: {
                "Content-Type": "application/json"
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data && data.total_cost !== undefined) {
                document.getElementById("total-cost").innerText = `Total Cost: $${data.total_cost.toFixed(2)}`;
            } else {
                document.getElementById("total-cost").innerText = "Total Cost: Unable to fetch.";
            }
        })
        .catch(error => {
            console.error("Error fetching total cost:", error);
            document.getElementById("total-cost").innerText = "Total Cost: Error fetching data.";
        });
    }



    