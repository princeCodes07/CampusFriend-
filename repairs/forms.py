from django import forms


class RepairContactForm(forms.Form):
    name = forms.CharField(max_length=150)
    phone_number = forms.CharField(max_length=20)
    whatsapp_number = forms.CharField(max_length=20, required=False)
    email = forms.EmailField(required=False)
    preferred_contact_method = forms.ChoiceField(
        choices=[
            ("Phone", "Phone"),
            ("WhatsApp", "WhatsApp"),
            ("SMS", "SMS"),
        ],
        required=False,
    )


class SpecialPhoneRepairForm(RepairContactForm):
    phone_type = forms.ChoiceField(choices=[("IPHONE", "iPhone"), ("ANDROID", "Android")])
    phone_model = forms.IntegerField(required=False)
    problem_description = forms.CharField(widget=forms.Textarea, required=True)
    image = forms.ImageField(required=False)
    customer_note = forms.CharField(widget=forms.Textarea, required=False)


class LaptopRepairForm(RepairContactForm):
    brand = forms.CharField(max_length=120, required=False)
    model = forms.CharField(max_length=120, required=False)
    problem_description = forms.CharField(widget=forms.Textarea, required=True)
    image = forms.ImageField(required=False)


class ElectronicsRepairForm(RepairContactForm):
    item_description = forms.CharField(max_length=200)
    problem_description = forms.CharField(widget=forms.Textarea, required=True)
    image = forms.ImageField(required=False)
