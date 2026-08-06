#!/usr/bin/env python
import os

content = '''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Wallet - GameArena</title>
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://js.paystack.co/v1/inline.js"></script>
</head>
<body class="min-h-screen bg-slate-950 text-white pb-28 md:pb-0">

<!-- ===== DESKTOP TOP NAV ===== -->
<nav class="hidden md:flex relative mx-auto max-w-7xl items-center justify-between px-6 py-5">
    <div class="flex items-center gap-3">
        <div class="flex h-12 w-12 items-center justify-center rounded-full bg-gradient-to-br from-emerald-400 to-cyan-400 shadow-2xl shadow-cyan-500/20">
            <span class="text-lg font-bold text-slate-950">G</span>
        </div>
        <div>
            <p class="text-sm uppercase tracking-[0.35em] text-emerald-300">GameArena</p>
            <p class="text-base font-semibold text-white/90">Mobile esports hub</p>
        </div>
    </div>

    <div class="flex items-center gap-6 text-sm text-slate-200">
        <a href="{{ url_for('home') }}" class="hover:text-white transition">Home</a>
        <a href="{{ url_for('tournaments_page') }}" class="hover:text-white transition">Tournament</a>
        <a href="{{ url_for('wallet') }}" class="text-emerald-300 font-semibold transition">Wallet</a>
        <a href="{{ url_for('profile') }}" class="hover:text-white transition">Profile</a>
        {% if current_user.is_admin %}
            <a href="{{ url_for('admin') }}" class="rounded-full bg-cyan-500 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-cyan-400">Admin</a>
        {% endif %}
        <a href="{{ url_for('logout') }}" class="rounded-full bg-slate-800 px-4 py-2 text-sm hover:bg-slate-700">Logout</a>
    </div>
</nav>

<!-- ===== MOBILE HEADER ===== -->
<div class="flex md:hidden items-center justify-between px-6 py-5">
    <div class="flex items-center gap-3">
        <div class="flex h-10 w-10 items-center justify-center rounded-full bg-gradient-to-br from-emerald-400 to-cyan-400">
            <span class="text-sm font-bold text-slate-950">G</span>
        </div>
        <p class="text-sm uppercase tracking-[0.3em] text-emerald-300">Wallet</p>
    </div>
    <button id="mobileMenuToggle" class="flex h-10 w-10 flex-col justify-center gap-1.5 rounded-full border border-white/10 bg-slate-950/80 p-2 md:hidden">
        <span class="block h-0.5 w-full rounded-full bg-white/80"></span>
        <span class="block h-0.5 w-full rounded-full bg-white/80"></span>
        <span class="block h-0.5 w-full rounded-full bg-white/80"></span>
    </button>
</div>

<!-- ===== MOBILE DROPDOWN MENU ===== -->
<div id="mobileMenu" class="fixed inset-x-4 top-20 z-50 hidden rounded-[28px] border border-white/10 bg-slate-950/95 p-4 shadow-2xl backdrop-blur-xl md:hidden">
    <div class="grid gap-3">
        <a href="{{ url_for('home') }}" class="rounded-3xl bg-slate-800 px-4 py-3 text-center text-sm hover:bg-slate-700">Home</a>
        <a href="{{ url_for('tournaments_page') }}" class="rounded-3xl bg-slate-800 px-4 py-3 text-center text-sm hover:bg-slate-700">Tournament</a>
        <a href="{{ url_for('wallet') }}" class="rounded-3xl bg-emerald-500 px-4 py-3 text-center text-sm font-semibold text-slate-950">Wallet</a>
        <a href="{{ url_for('profile') }}" class="rounded-3xl bg-slate-800 px-4 py-3 text-center text-sm hover:bg-slate-700">Profile</a>
        {% if current_user.is_admin %}
            <a href="{{ url_for('admin') }}" class="rounded-3xl bg-cyan-500 px-4 py-3 text-center text-sm font-semibold text-slate-950">Admin</a>
        {% endif %}
        <a href="{{ url_for('logout') }}" class="rounded-3xl bg-slate-800 px-4 py-3 text-center text-sm hover:bg-slate-700">Logout</a>
    </div>
</div>

<!-- ===== FLASH MESSAGES ===== -->
{% with messages = get_flashed_messages(with_categories=true) %}
{% if messages %}
<div class="mx-auto max-w-7xl px-6 mb-4">
    {% for category, message in messages %}
    <div class="rounded-[28px] border {% if category == 'success' %}border-emerald-500/30 bg-emerald-500/15{% else %}border-red-500/30 bg-red-500/15{% endif %} p-4 text-center">
        <p class="{% if category == 'success' %}text-emerald-200{% else %}text-red-200{% endif %}">{{ message }}</p>
    </div>
    {% endfor %}
</div>
{% endif %}
{% endwith %}

<!-- ===== MAIN CONTENT ===== -->
<main class="mx-auto max-w-7xl px-6 py-8 space-y-8">
