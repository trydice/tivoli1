document.addEventListener("DOMContentLoaded", function () {
    // Initialize Stripe
    const stripe = Stripe('pk_test_Ujwxvk3zBxt8yokfEFa8wSnX'); // Replace with your actual Stripe public key
    const elements = stripe.elements();

    // Custom styling can be passed to options when creating an Element.
    const style = {
        base: {
            color: "#32325d",
            fontFamily: '"Helvetica Neue", Helvetica, sans-serif',
            fontSmoothing: "antialiased",
            fontSize: "16px",
            "::placeholder": {
                color: "#a0aec0"
            }
        },
        invalid: {
            color: "#fa755a",
            iconColor: "#fa755a"
        }
    };

    // Create an instance of the card Element.
    const card = elements.create("card", { style: style });

    // Add an instance of the card Element into the `card-element` <div>.
    card.mount("#card-element");

    // Handle real-time validation errors from the card Element.
    card.on('change', function(event) {
        const displayError = document.getElementById('card-errors');
        if (event.error) {
            displayError.textContent = event.error.message;
        } else {
            displayError.textContent = '';
        }
    });

    // Handle form submission.
    const form = document.getElementById('checkoutForm');
    form.addEventListener('submit', function(event) {
        event.preventDefault();

        // Disable the submit button to prevent repeated clicks
        form.querySelector('button').disabled = true;

        // Collect form data
        const formData = new FormData(form);
        const data = {
            user_name: formData.get('user_name'),
            user_email: formData.get('user_email'),
            user_address: formData.get('user_address'),
            delivery_datetime: formData.get('delivery_datetime'),
            contact_number: formData.get('contact_number')
        };

        // Validate delivery_datetime (client-side)
        const deliveryDateTime = new Date(data.delivery_datetime);
        const now = new Date();
        const diffInMs = deliveryDateTime - now;
        const diffInHours = diffInMs / (1000 * 60 * 60);
        if (diffInHours < 24) {
            document.getElementById('datetime-error').style.display = 'block';
            form.querySelector('button').disabled = false;
            return;
        } else {
            document.getElementById('datetime-error').style.display = 'none';
        }

        // Create Payment Method
        stripe.createPaymentMethod({
            type: 'card',
            card: card,
            billing_details: {
                name: data.user_name,
                email: data.user_email,
                address: {
                    line1: data.user_address
                },
                phone: data.contact_number
            }
        }).then(function(result) {
            if (result.error) {
                // Show error in payment form
                const errorElement = document.getElementById('card-errors');
                errorElement.textContent = result.error.message;
                form.querySelector('button').disabled = false;
            } else {
                // Send paymentMethod.id and form data to the server
                fetch('/create-payment-intent', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify({
                        payment_method_id: result.paymentMethod.id,
                        ...data
                    })
                }).then(function(response) {
                    return response.json();
                }).then(function(serverResponse) {
                    if (serverResponse.error) {
                        // Show error from server on payment form
                        const errorElement = document.getElementById('card-errors');
                        errorElement.textContent = serverResponse.error;
                        form.querySelector('button').disabled = false;
                    } else {
                        if (serverResponse.requires_action) {
                            // Use Stripe.js to handle required card actions
                            stripe.handleCardAction(serverResponse.payment_intent_client_secret)
                                .then(function(result) {
                                    if (result.error) {
                                        // Show error in payment form
                                        const errorElement = document.getElementById('card-errors');
                                        errorElement.textContent = result.error.message;
                                        form.querySelector('button').disabled = false;
                                    } else {
                                        // The card action has been handled
                                        // The PaymentIntent can be confirmed again on the server
                                        fetch('/confirm-payment', {
                                            method: 'POST',
                                            headers: {
                                                'Content-Type': 'application/json'
                                            },
                                            body: JSON.stringify({
                                                payment_intent_id: result.paymentIntent.id
                                            })
                                        }).then(function(confirmResponse) {
                                            return confirmResponse.json();
                                        }).then(function(confirmData) {
                                            if (confirmData.error) {
                                                // Show error from server on payment form
                                                const errorElement = document.getElementById('card-errors');
                                                errorElement.textContent = confirmData.error;
                                                form.querySelector('button').disabled = false;
                                            } else {
                                                // Payment succeeded, redirect to success page
                                                window.location.href = '/success';
                                            }
                                        });
                                    }
                                });
                        } else {
                            // No additional actions required, payment succeeded
                            window.location.href = '/success';
                        }
                    }
                });
            }
        });
    });


});
