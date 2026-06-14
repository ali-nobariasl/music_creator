from django.shortcuts import render

# Create your views here.
from django.http import HttpResponse

def index(request):
    print("Hello, world. You're at the adhd_app index.")
    return HttpResponse("Hello, world. You're at the adhd_app index.")