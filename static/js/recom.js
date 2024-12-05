// Email Modal Logic
function openEmailModal() {
    const selectedRec = document.querySelector('input[name="selected_rec"]:checked');
    if (selectedRec) {
        console.log('Selected Rec Value:', selectedRec.value); // Debugging
        document.getElementById('modal-rec-index').value = selectedRec.value;
        document.getElementById('emailModal').style.display = 'flex';
    } else {
        alert("Please select a recommendation before checking out.");
    }
}

function closeEmailModal() {
    document.getElementById('emailModal').style.display = 'none';
}

window.onclick = function (event) {
    if (event.target == document.getElementById('emailModal')) {
        closeEmailModal();
    }
};

function selectCard(index) {
    // Programmatically select the radio button
    const radioButton = document.getElementById(`rec-${index}`);
    radioButton.checked = true;

    // Add visual feedback for the selected card (optional)
    document.querySelectorAll('.circle-label').forEach(label => {
        label.style.boxShadow = '0 4px 6px rgba(0, 0, 0, 0.2)'; // Reset others
        label.style.transform = 'scale(1)';
    });
    const selectedLabel = document.querySelector(`label[for="rec-${index}"]`);
    selectedLabel.style.boxShadow = '0 6px 12px rgba(0, 0, 0, 0.4)';
    selectedLabel.style.transform = 'scale(1.15)';
}
