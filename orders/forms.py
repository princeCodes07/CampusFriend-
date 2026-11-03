from decimal import Decimal
import re

from django import forms

from .delivery import LOCATION_CHOICES
from .models import Order


class AddToCartForm(forms.Form):
    quantity = forms.IntegerField(
        min_value=1,
        max_value=2147483647,
        error_messages={
            "required": "Choose a quantity to add.",
            "invalid": "Enter a whole number for the quantity.",
            "min_value": "Choose at least 1 item.",
            "max_value": "Choose a smaller quantity.",
        },
    )


class CheckoutForm(forms.ModelForm):
    checkout_token = forms.UUIDField(widget=forms.HiddenInput)
    delivery_area = forms.ChoiceField(
        label="Select location", choices=(("", "Select location"), *LOCATION_CHOICES),
        help_text="Your order summary updates for the location you select.",
    )

    class Meta:
        model = Order
        fields = ("customer_name", "customer_phone", "customer_email", "delivery_area", "delivery_location", "landmark", "delivery_notes")
        labels = {
            "customer_name": "Full name", "customer_phone": "Phone number",
            "customer_email": "Email (optional)", "delivery_location": "Delivery address / hall / hostel",
            "landmark": "Nearby landmark", "delivery_notes": "Delivery notes (optional)",
        }
        help_texts = {
            "customer_phone": "Use your Ghana number or an international number beginning with +.",
            "delivery_location": "Required for delivery; optional for pickup at Palms Eatery. Include your room number.",
            "landmark": "Required for delivery; optional for pickup.",
        }
        widgets = {
            "customer_name": forms.TextInput(attrs={"autocomplete": "name"}),
            "customer_phone": forms.TextInput(attrs={"type": "tel", "autocomplete": "tel"}),
            "customer_email": forms.EmailInput(attrs={"autocomplete": "email"}),
            "delivery_location": forms.TextInput(attrs={"autocomplete": "street-address"}),
            "delivery_notes": forms.Textarea(attrs={"rows": 3}),
        }

    def clean_customer_phone(self):
        phone = re.sub(r"[\s()\-]", "", self.cleaned_data["customer_phone"])
        if re.fullmatch(r"0[1-9][0-9]{8}", phone):
            return "+233" + phone[1:]
        if re.fullmatch(r"\+[1-9][0-9]{7,14}", phone):
            return phone
        raise forms.ValidationError("Enter a valid Ghana phone number or include your country code, for example +233.")

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("delivery_area") and cleaned["delivery_area"] != "pickup":
            for field, message in (("delivery_location", "Enter your delivery address, hall or hostel."),
                                   ("landmark", "Enter a nearby landmark to help us find you.")):
                if not cleaned.get(field) and field not in self.errors:
                    self.add_error(field, message)
        return cleaned


class DeliveryQuoteForm(forms.Form):
    delivery_fee = forms.DecimalField(
        label="Confirmed delivery fee (GHS)", max_digits=10, decimal_places=2,
        min_value=Decimal("0.00"), help_text="Enter the agreed delivery fee. Pickup must be 0.00. The server calculates the final total.",
    )
