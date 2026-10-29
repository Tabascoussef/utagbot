import json
import time
import logging
import asyncio
from aiohttp import web, ClientSession, ClientTimeout
from typing import Dict, Any, Optional
import config
import database

# Tashqi bot va userbot workerlariga murojaat qilish uchun
bot_instance = None
running_userbots_ref = {}

def set_broadcast_context(bot, running_userbots):
    global bot_instance, running_userbots_ref
    bot_instance = bot
    running_userbots_ref = running_userbots

# Telegram Web App HTML/CSS/JS interfeyzi
HTML_PAGE = """<!DOCTYPE html>
<html lang="uz">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=no, viewport-fit=cover">
    <title>UTAG Admin Dashboard</title>
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-dark: #121522;
            --surface: #1a1e30;
            --surface-hover: #22273d;
            --surface-glass: rgba(26, 30, 48, 0.75);
            --border: rgba(255, 255, 255, 0.07);
            --border-hover: rgba(255, 255, 255, 0.15);
            --border-glow: rgba(99, 102, 241, 0.35);

            --blue-hero: linear-gradient(135deg, #3d5bf6 0%, #2842c9 50%, #1c3098 100%);
            --coral-neon: linear-gradient(135deg, #ff5277 0%, #fa658d 50%, #f77062 100%);
            --cyan-neon: #00f2fe;
            --purple-neon: #a855f7;
            --green-neon: #10b981;
            --danger: #f85149;

            --text-white: #ffffff;
            --text-muted: #8e95af;
            --text-sub: #adb5bd;
            --radius-card: 22px;
        }

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
            -webkit-tap-highlight-color: transparent;
        }

        body {
            background-color: var(--bg-dark);
            background-image: 
                radial-gradient(circle at 15% 0%, rgba(99, 102, 241, 0.18) 0%, transparent 45%),
                radial-gradient(circle at 85% 25%, rgba(244, 63, 94, 0.12) 0%, transparent 40%),
                radial-gradient(circle at 50% 85%, rgba(0, 242, 254, 0.08) 0%, transparent 45%);
            color: var(--text-white);
            min-height: 100vh;
            padding: 16px 18px 100px 18px;
            overflow-x: hidden;
        }

        /* --- APP HEADER --- */
        .app-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 20px;
            padding-top: 4px;
        }

        .header-icon-btn {
            width: 40px;
            height: 40px;
            border-radius: 12px;
            background: var(--surface);
            border: 1px solid var(--border);
            color: var(--text-muted);
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            transition: all 0.2s;
        }

        .header-icon-btn:active {
            transform: scale(0.95);
        }

        .header-title {
            font-size: 19px;
            font-weight: 700;
            letter-spacing: -0.3px;
            color: var(--text-white);
        }

        .profile-avatar-wrap {
            position: relative;
            cursor: pointer;
        }

        .profile-avatar {
            width: 42px;
            height: 42px;
            border-radius: 50%;
            border: 2px solid #3b82f6;
            background: linear-gradient(135deg, #1e293b, #334155);
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            font-size: 15px;
            color: white;
            box-shadow: 0 0 12px rgba(59, 130, 246, 0.35);
        }

        .online-dot {
            position: absolute;
            bottom: 1px;
            right: 1px;
            width: 10px;
            height: 10px;
            background: #10b981;
            border: 2px solid var(--bg-dark);
            border-radius: 50%;
        }

        /* --- TAB CONTENT CONTAINERS --- */
        .tab-pane {
            display: none;
            animation: fadeIn 0.25s ease-out;
        }

        .tab-pane.active {
            display: block;
        }

        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(6px); }
            to { opacity: 1; transform: translateY(0); }
        }

        /* --- SCREEN 1: HERO CREDIT-STYLE CARD --- */
        .hero-card {
            background: var(--blue-hero);
            border-radius: var(--radius-card);
            padding: 22px 20px;
            color: white;
            position: relative;
            overflow: hidden;
            box-shadow: 0 18px 38px -10px rgba(45, 75, 226, 0.5);
            margin-bottom: 20px;
            border: 1px solid rgba(255, 255, 255, 0.15);
        }

        .hero-card::before {
            content: '';
            position: absolute;
            top: -50px;
            right: -40px;
            width: 160px;
            height: 160px;
            background: radial-gradient(circle, rgba(255, 255, 255, 0.18) 0%, transparent 70%);
            border-radius: 50%;
        }

        .hero-card-top {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 22px;
            position: relative;
            z-index: 1;
        }

        .card-circles {
            display: flex;
            align-items: center;
        }

        .circle-yellow {
            width: 30px;
            height: 30px;
            border-radius: 50%;
            background: rgba(255, 214, 0, 0.9);
        }

        .circle-cyan {
            width: 30px;
            height: 30px;
            border-radius: 50%;
            background: rgba(0, 242, 254, 0.75);
            margin-left: -13px;
        }

        .hero-user-info {
            text-align: right;
        }

        .hero-user-name {
            font-size: 17px;
            font-weight: 700;
            letter-spacing: -0.2px;
        }

        .hero-user-number {
            font-size: 12px;
            color: rgba(255, 255, 255, 0.75);
            letter-spacing: 1.5px;
            margin-top: 3px;
            font-family: monospace;
        }

        .hero-card-bottom {
            display: flex;
            justify-content: space-between;
            align-items: flex-end;
            position: relative;
            z-index: 1;
        }

        .badge-superadmin {
            background: rgba(255, 255, 255, 0.2);
            backdrop-filter: blur(8px);
            padding: 5px 12px;
            border-radius: 20px;
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            border: 1px solid rgba(255, 255, 255, 0.25);
            display: inline-flex;
            align-items: center;
            gap: 5px;
        }

        .hero-stars-section {
            position: relative;
            z-index: 1;
            background: rgba(10, 16, 45, 0.32);
            border: 1px solid rgba(255, 255, 255, 0.16);
            border-radius: 16px;
            padding: 12px 14px;
            margin-bottom: 14px;
            backdrop-filter: blur(10px);
        }

        .hero-stars-top {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }

        .hero-stars-label {
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.6px;
            color: rgba(255, 255, 255, 0.8);
            display: flex;
            align-items: center;
            gap: 5px;
        }

        .hero-stars-main {
            font-size: 24px;
            font-weight: 800;
            color: #fde047;
            letter-spacing: -0.5px;
            display: flex;
            align-items: baseline;
            gap: 6px;
            text-shadow: 0 2px 12px rgba(250, 204, 21, 0.45);
        }

        .hero-rates-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 8px;
        }

        .hero-rate-pill {
            background: rgba(255, 255, 255, 0.1);
            border: 1px solid rgba(255, 255, 255, 0.14);
            border-radius: 12px;
            padding: 8px 6px;
            text-align: center;
            display: flex;
            flex-direction: column;
            gap: 2px;
        }

        .hero-rate-curr {
            font-size: 10px;
            font-weight: 700;
            color: rgba(255, 255, 255, 0.75);
            letter-spacing: 0.3px;
        }

        .hero-rate-val {
            font-size: 13px;
            font-weight: 800;
            color: #ffffff;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .hero-rate-sub {
            font-size: 9.5px;
            font-weight: 600;
            color: #bae6fd;
            opacity: 0.9;
            white-space: nowrap;
        }

        .card-dots {
            display: flex;
            gap: 6px;
            justify-content: center;
            margin-top: 14px;
        }

        .card-dot {
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background: rgba(255, 255, 255, 0.25);
        }

        .card-dot.active {
            background: #ffffff;
            width: 16px;
            border-radius: 10px;
        }

        /* --- STAT METRICS GRID (3-COLUMN LIKE SCREEN 1) --- */
        .metrics-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 10px;
            margin-bottom: 22px;
        }

        .metric-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 18px;
            padding: 14px 10px;
            display: flex;
            flex-direction: column;
            align-items: center;
            text-align: center;
            backdrop-filter: blur(12px);
            transition: transform 0.2s;
        }

        .metric-card:active {
            transform: scale(0.97);
        }

        .metric-icon-box {
            width: 36px;
            height: 36px;
            border-radius: 10px;
            background: rgba(255, 255, 255, 0.04);
            border: 1px solid var(--border);
            display: flex;
            align-items: center;
            justify-content: center;
            color: var(--text-muted);
            margin-bottom: 8px;
        }

        .metric-title {
            font-size: 11px;
            font-weight: 500;
            color: var(--text-muted);
            margin-bottom: 4px;
        }

        .metric-val {
            font-size: 16px;
            font-weight: 800;
            color: var(--text-white);
            letter-spacing: -0.3px;
        }

        /* --- CONTACTS / USER CAROUSEL (SCREEN 2 TOP) --- */
        .section-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 12px;
        }

        .section-title {
            font-size: 14px;
            font-weight: 600;
            color: var(--text-muted);
        }

        .section-link {
            font-size: 12px;
            color: #3b82f6;
            text-decoration: none;
            cursor: pointer;
            font-weight: 600;
        }

        .contacts-scroll {
            display: flex;
            gap: 12px;
            overflow-x: auto;
            padding-bottom: 8px;
            margin-bottom: 20px;
            scrollbar-width: none;
            -webkit-overflow-scrolling: touch;
        }

        .contacts-scroll::-webkit-scrollbar {
            display: none;
        }

        .contact-pill {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 8px 14px;
            display: flex;
            align-items: center;
            gap: 10px;
            min-width: 145px;
            flex-shrink: 0;
            cursor: pointer;
            transition: all 0.2s;
        }

        .contact-pill:active {
            transform: scale(0.96);
        }

        .contact-avatar {
            width: 34px;
            height: 34px;
            border-radius: 50%;
            border: 2px solid #10b981;
            background: #23293f;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 13px;
            font-weight: 700;
            color: white;
            flex-shrink: 0;
        }

        .contact-info {
            overflow: hidden;
        }

        .contact-name {
            font-size: 12px;
            font-weight: 700;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }

        .contact-sub {
            font-size: 11px;
            color: #10b981;
            font-weight: 600;
        }

        /* --- NEON GRAPH CARD (SCREEN 1 & 2 CHART) --- */
        .chart-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius-card);
            padding: 18px;
            margin-bottom: 22px;
            position: relative;
            overflow: hidden;
        }

        .chart-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 14px;
        }

        .chart-title {
            font-size: 13px;
            font-weight: 600;
            color: var(--text-muted);
        }

        .chart-tag {
            font-size: 12px;
            font-weight: 700;
            color: var(--text-white);
            background: rgba(255, 255, 255, 0.06);
            padding: 3px 10px;
            border-radius: 12px;
        }

        .neon-chart-svg {
            width: 100%;
            height: 125px;
            overflow: visible;
        }

        .chart-tooltip-badge {
            position: absolute;
            top: 48px;
            left: 50%;
            transform: translateX(-50%);
            background: rgba(18, 21, 34, 0.9);
            border: 1px solid rgba(0, 242, 254, 0.4);
            border-radius: 20px;
            padding: 4px 10px;
            font-size: 11px;
            font-weight: 800;
            color: var(--cyan-neon);
            box-shadow: 0 4px 12px rgba(0, 242, 254, 0.25);
            display: flex;
            align-items: center;
            gap: 4px;
        }

        .chart-legend {
            display: flex;
            justify-content: space-around;
            margin-top: 14px;
            padding-top: 10px;
            border-top: 1px solid rgba(255, 255, 255, 0.05);
            font-size: 12px;
        }

        .legend-item {
            display: flex;
            align-items: center;
            gap: 6px;
            color: var(--text-sub);
        }

        .legend-dot-pink {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #ff5277;
            box-shadow: 0 0 6px #ff5277;
        }

        .legend-dot-cyan {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: var(--cyan-neon);
            box-shadow: 0 0 6px var(--cyan-neon);
        }

        /* --- SCREEN 2: SEARCH & USERS LIST --- */
        .search-pill {
            position: relative;
            margin-bottom: 14px;
        }

        .search-pill input {
            width: 100%;
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 13px 14px 13px 42px;
            color: var(--text-white);
            font-size: 13px;
            outline: none;
            transition: border-color 0.2s, box-shadow 0.2s;
        }

        .search-pill input:focus {
            border-color: #3b82f6;
            box-shadow: 0 0 12px rgba(59, 130, 246, 0.2);
        }

        .search-pill svg {
            position: absolute;
            left: 14px;
            top: 50%;
            transform: translateY(-50%);
            stroke: var(--text-muted);
        }

        /* GROUPS & CHATS SUB-TABS (XUDDI SKRINSHOTDEK UNDERLINE BILAN) */
        .groups-tab-nav {
            display: flex;
            align-items: center;
            gap: 20px;
            border-bottom: 1.5px solid rgba(255, 255, 255, 0.12);
            margin-bottom: 16px;
            padding: 0 4px;
            overflow-x: auto;
            scrollbar-width: none;
        }

        .groups-tab-nav::-webkit-scrollbar {
            display: none;
        }

        .groups-tab-btn {
            background: none;
            border: none;
            outline: none;
            font-family: inherit;
            font-size: 13.5px;
            font-weight: 600;
            color: #94a3b8;
            padding: 10px 4px 12px 4px;
            cursor: pointer;
            position: relative;
            transition: color 0.2s ease;
            display: flex;
            align-items: center;
            gap: 6px;
            white-space: nowrap;
        }

        .groups-tab-btn:hover {
            color: #f1f5f9;
        }

        .groups-tab-btn.active {
            color: #38bdf8;
            font-weight: 700;
        }

        .groups-tab-btn.active::after {
            content: '';
            position: absolute;
            bottom: -1.5px;
            left: 0;
            right: 0;
            height: 3px;
            background: #38bdf8;
            border-radius: 3px 3px 0 0;
            box-shadow: 0 0 10px rgba(56, 189, 248, 0.6);
        }

        .groups-tab-badge {
            font-size: 11px;
            padding: 2px 7px;
            border-radius: 12px;
            background: rgba(255, 255, 255, 0.08);
            color: #94a3b8;
            font-weight: 600;
            transition: all 0.2s;
        }

        .groups-tab-btn.active .groups-tab-badge {
            background: rgba(56, 189, 248, 0.2);
            color: #38bdf8;
        }

        .users-list-container {
            display: flex;
            flex-direction: column;
            gap: 12px;
        }

        .user-card-item {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius-card);
            padding: 16px;
            display: flex;
            flex-direction: column;
            gap: 12px;
            transition: all 0.2s;
        }

        .user-item-top {
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .user-avatar-group {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .user-item-avatar {
            width: 44px;
            height: 44px;
            border-radius: 50%;
            border: 2px solid #3b82f6;
            background: #252a40;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 800;
            font-size: 16px;
            color: white;
            flex-shrink: 0;
        }

        .user-item-avatar.active-sub {
            border-color: #10b981;
            box-shadow: 0 0 10px rgba(16, 185, 129, 0.3);
        }

        .user-name-title {
            font-size: 14px;
            font-weight: 700;
            color: var(--text-white);
        }

        .user-username-badge {
            font-size: 12px;
            color: #38bdf8;
            font-weight: 600;
            margin-top: 2px;
            display: flex;
            align-items: center;
            gap: 4px;
        }

        .user-username-badge a {
            color: #38bdf8;
            text-decoration: none;
        }

        .user-meta-sub {
            font-size: 12px;
            color: var(--text-muted);
            margin-top: 2px;
        }

        .badge-status {
            font-size: 11px;
            font-weight: 700;
            padding: 4px 10px;
            border-radius: 20px;
            letter-spacing: 0.3px;
        }

        .badge-status.active {
            background: rgba(16, 185, 129, 0.15);
            color: #10b981;
            border: 1px solid rgba(16, 185, 129, 0.3);
        }

        .badge-status.expired {
            background: rgba(248, 81, 73, 0.12);
            color: var(--danger);
            border: 1px solid rgba(248, 81, 73, 0.3);
        }

        .badge-status.superadmin {
            background: rgba(251, 191, 36, 0.18);
            color: #fbbf24;
            border: 1px solid rgba(251, 191, 36, 0.4);
        }

        .badge-status.admin {
            background: rgba(168, 85, 247, 0.18);
            color: #c084fc;
            border: 1px solid rgba(168, 85, 247, 0.4);
        }

        .btn-promote-admin {
            background: rgba(168, 85, 247, 0.18);
            color: #d8b4fe;
            border: 1px solid rgba(168, 85, 247, 0.35);
        }
        .btn-promote-admin:hover {
            background: rgba(168, 85, 247, 0.3);
            color: #ffffff;
        }

        .btn-demote-admin {
            background: rgba(239, 68, 68, 0.15);
            color: #fca5a5;
            border: 1px solid rgba(239, 68, 68, 0.35);
        }
        .btn-demote-admin:hover {
            background: rgba(239, 68, 68, 0.25);
            color: #ffffff;
        }

        .btn-groups {
            background: rgba(56, 189, 248, 0.15);
            color: #38bdf8;
            border: 1px solid rgba(56, 189, 248, 0.3);
        }
        .btn-groups:hover {
            background: rgba(56, 189, 248, 0.25);
            color: #ffffff;
        }

        .user-info-grid {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 8px;
            background: rgba(0, 0, 0, 0.2);
            padding: 10px 12px;
            border-radius: 12px;
            border: 1px solid rgba(255, 255, 255, 0.04);
            font-size: 12px;
        }

        .info-cell span {
            color: var(--text-muted);
            display: block;
            margin-bottom: 2px;
        }

        .info-cell strong {
            color: var(--text-white);
            font-weight: 600;
        }

        .user-actions-row {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }

        .action-pill-btn {
            border: none;
            cursor: pointer;
            border-radius: 10px;
            padding: 8px 13px;
            font-size: 11px;
            font-weight: 700;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 4px;
            transition: all 0.2s;
        }

        .action-pill-btn:active {
            transform: scale(0.95);
        }

        .btn-add-7 {
            background: linear-gradient(135deg, #059669, #10b981);
            color: white;
        }

        .btn-add-30 {
            background: linear-gradient(135deg, #2563eb, #3b82f6);
            color: white;
        }

        .btn-custom {
            background: linear-gradient(135deg, #0891b2, #06b6d4);
            color: white;
        }

        .btn-revoke {
            background: rgba(248, 81, 73, 0.15);
            color: var(--danger);
            border: 1px solid rgba(248, 81, 73, 0.3);
        }

        /* --- SCREEN 3: PROFILE & BROADCAST REKLAMA --- */
        .profile-hero-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius-card);
            padding: 20px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 20px;
        }

        .profile-hero-left {
            display: flex;
            align-items: center;
            gap: 14px;
        }

        .profile-avatar-large {
            width: 56px;
            height: 56px;
            border-radius: 50%;
            border: 3px solid #3b82f6;
            background: linear-gradient(135deg, #1e293b, #334155);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 22px;
            font-weight: 800;
            color: white;
        }

        .btn-upgrade-badge {
            background: var(--coral-neon);
            color: white;
            border-radius: 14px;
            padding: 8px 14px;
            font-size: 12px;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 5px;
            border: none;
            box-shadow: 0 4px 15px rgba(255, 82, 119, 0.35);
        }

        .status-toggle-box {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 18px;
            padding: 16px;
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            justify-content: space-between;
        }

        .toggle-switch-ui {
            width: 48px;
            height: 26px;
            background: #2b3149;
            border-radius: 20px;
            position: relative;
            cursor: pointer;
            transition: background 0.25s, box-shadow 0.25s;
        }

        .toggle-switch-ui.active {
            background: #3b5bf6;
            box-shadow: 0 0 12px rgba(59, 91, 246, 0.5);
        }

        .toggle-thumb-ui {
            width: 20px;
            height: 20px;
            border-radius: 50%;
            background: white;
            position: absolute;
            top: 3px;
            left: 3px;
            transition: transform 0.25s cubic-bezier(0.16, 1, 0.3, 1);
        }

        .toggle-switch-ui.active .toggle-thumb-ui {
            transform: translateX(22px);
        }

        .broadcast-card {
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: var(--radius-card);
            padding: 18px;
            margin-bottom: 20px;
        }

        .broadcast-textarea {
            width: 100%;
            height: 120px;
            background: rgba(18, 21, 34, 0.8);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 12px 14px;
            color: white;
            font-size: 13px;
            outline: none;
            resize: vertical;
            margin-top: 10px;
            transition: border-color 0.2s;
        }

        .broadcast-textarea:focus {
            border-color: #3b82f6;
        }

        .btn-send-neon {
            width: 100%;
            background: var(--coral-neon);
            color: white;
            padding: 14px;
            font-size: 14px;
            font-weight: 700;
            border-radius: 16px;
            border: none;
            cursor: pointer;
            box-shadow: 0 8px 24px rgba(255, 82, 119, 0.4);
            margin-top: 14px;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            transition: transform 0.2s;
        }

        .btn-send-neon:active {
            transform: scale(0.98);
        }

        .report-box {
            display: none;
            background: rgba(0, 0, 0, 0.3);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 12px;
            font-size: 12px;
            margin-top: 14px;
            line-height: 1.6;
        }

        /* --- FLOATING BOTTOM NAVIGATION DOCK (MATCHING THE 3 SCREENS) --- */
        .bottom-dock {
            position: fixed;
            bottom: 16px;
            left: 20px;
            right: 20px;
            height: 64px;
            background: rgba(22, 26, 42, 0.88);
            backdrop-filter: blur(24px);
            -webkit-backdrop-filter: blur(24px);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 30px;
            display: flex;
            align-items: center;
            justify-content: space-around;
            padding: 0 12px;
            box-shadow: 0 20px 45px rgba(0, 0, 0, 0.6);
            z-index: 999;
        }

        .dock-btn {
            background: transparent;
            border: none;
            color: var(--text-muted);
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            width: 44px;
            height: 44px;
            border-radius: 14px;
            transition: all 0.2s cubic-bezier(0.16, 1, 0.3, 1);
        }

        .dock-btn:active {
            transform: scale(0.9);
        }

        .dock-btn.active {
            color: var(--cyan-neon);
        }

        /* O'RTADAGI YORQIN PUSHTI/KORAL FLOATING TUGMA */
        .dock-center-action {
            width: 48px;
            height: 48px;
            border-radius: 17px;
            background: var(--coral-neon);
            color: white;
            border: none;
            display: flex;
            align-items: center;
            justify-content: center;
            cursor: pointer;
            box-shadow: 0 8px 24px rgba(255, 82, 119, 0.5);
            transition: transform 0.2s, box-shadow 0.2s;
        }

        .dock-center-action:active {
            transform: scale(0.92);
        }

        /* --- TOAST BILDIRISHNOMA --- */
        .toast-popup {
            position: fixed;
            top: 20px;
            left: 50%;
            transform: translateX(-50%) translateY(-100px);
            background: #10b981;
            color: white;
            padding: 10px 22px;
            border-radius: 30px;
            font-size: 13px;
            font-weight: 700;
            box-shadow: 0 6px 20px rgba(0, 0, 0, 0.5);
            transition: transform 0.3s cubic-bezier(0.18, 0.89, 0.32, 1.28);
            z-index: 10000;
        }

        .toast-popup.show {
            transform: translateX(-50%) translateY(0);
        }

        .toast-popup.error {
            background: var(--danger);
        }

        .empty-state {
            text-align: center;
            padding: 40px 10px;
            color: var(--text-muted);
            font-size: 13px;
        }
    </style>
</head>
<body>

    <!-- TOP HEADER -->
    <div class="app-header">
        <button class="header-icon-btn" onclick="switchNavTab('tab-dashboard')">
            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
                <line x1="4" y1="8" x2="20" y2="8"></line>
                <line x1="4" y1="16" x2="20" y2="16"></line>
            </svg>
        </button>
        <span class="header-title" id="pageTitle">Dashboard</span>
        <div class="profile-avatar-wrap" onclick="switchNavTab('tab-broadcast')">
            <div class="profile-avatar" id="headerAvatar">YA</div>
            <div class="online-dot"></div>
        </div>
    </div>

    <!-- 1. DASHBOARD TAB (SCREEN 1 & 2 STYLE) -->
    <div id="tab-dashboard" class="tab-pane active">

        <!-- HERO CREDIT-CARD STYLE (STARS BALANCE + TON / USD / UZS RATIOS) -->
        <div class="hero-card">
            <div class="hero-card-top" style="margin-bottom: 14px;">
                <div class="card-circles">
                    <div class="circle-yellow"></div>
                    <div class="circle-cyan"></div>
                </div>
                <div class="hero-user-info">
                    <div class="hero-user-name" id="heroAdminName">Yusuf Azimov</div>
                    <div class="hero-user-number">1784 •••• •••• 3012</div>
                </div>
            </div>

            <!-- BOT HISOBIDAGI STARSLAR VA VALYUTA NISBATI -->
            <div class="hero-stars-section">
                <div class="hero-stars-top">
                    <div class="hero-stars-label">⭐️ Bot Stars Hisobi</div>
                    <div class="hero-stars-main">
                        <span>⭐️</span>
                        <span id="heroStarsCount">0</span>
                        <span style="font-size: 12px; font-weight: 600; color: rgba(255,255,255,0.85);">Stars</span>
                    </div>
                </div>
                <div class="hero-rates-grid">
                    <div class="hero-rate-pill">
                        <span class="hero-rate-curr">💎 TON</span>
                        <span class="hero-rate-val" id="heroTonVal">0.000 TON</span>
                        <span class="hero-rate-sub" id="heroTonRatio">100 ⭐️ ≈ 0.25 TON</span>
                    </div>
                    <div class="hero-rate-pill">
                        <span class="hero-rate-curr">💵 USD</span>
                        <span class="hero-rate-val" id="heroUsdVal">$0.00</span>
                        <span class="hero-rate-sub" id="heroUsdRatio">100 ⭐️ = $1.30</span>
                    </div>
                    <div class="hero-rate-pill">
                        <span class="hero-rate-curr">🇺🇿 UZS</span>
                        <span class="hero-rate-val" id="heroUzsVal">0 so'm</span>
                        <span class="hero-rate-sub" id="heroUzsRatio">100 ⭐️ ≈ 16.7k</span>
                    </div>
                </div>
            </div>

            <div class="hero-card-bottom">
                <span class="badge-superadmin">👑 Super Admin</span>
                <span style="font-size: 11px; opacity: 0.9; font-weight: 600;" id="heroLiveRateInfo">⚡️ Cheksiz Obuna</span>
            </div>
        </div>
        <div class="card-dots">
            <div class="card-dot active"></div>
            <div class="card-dot"></div>
            <div class="card-dot"></div>
        </div>

        <div style="height: 18px;"></div>

        <!-- 3-COLUMN METRICS GRID (MATCHING SCREEN 1) -->
        <div class="metrics-grid">
            <div class="metric-card" style="cursor: pointer;" onclick="switchNavTab('tab-users'); switchUsersSubTab('unsubscribed');">
                <div class="metric-icon-box">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                        <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
                        <circle cx="9" cy="7" r="4"></circle>
                    </svg>
                </div>
                <div class="metric-title">Jami userlar</div>
                <div class="metric-val" id="stat-total">0</div>
            </div>

            <div class="metric-card" style="cursor: pointer;" onclick="switchNavTab('tab-users'); switchUsersSubTab('subscribed');">
                <div class="metric-icon-box">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#10b981" stroke-width="2" stroke-linecap="round">
                        <rect x="2" y="5" width="20" height="14" rx="2"></rect>
                        <line x1="2" y1="10" x2="22" y2="10"></line>
                    </svg>
                </div>
                <div class="metric-title">Faol obuna</div>
                <div class="metric-val" id="stat-active" style="color: #10b981;">0</div>
            </div>

            <div class="metric-card">
                <div class="metric-icon-box">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#00f2fe" stroke-width="2" stroke-linecap="round">
                        <circle cx="12" cy="12" r="10"></circle>
                        <polyline points="12 6 12 12 16 14"></polyline>
                    </svg>
                </div>
                <div class="metric-title">O'rtacha tezlik</div>
                <div class="metric-val" id="stat-speed">2.0s</div>
            </div>
        </div>

        <!-- TOP PROGRESS CONTACTS (SCREEN 2) -->
        <div class="section-header">
            <span class="section-title">Faol userbotlar</span>
            <span class="section-link" onclick="switchNavTab('tab-users')">Barchasi &rarr;</span>
        </div>
        <div class="contacts-scroll" id="contactsCarousel">
            <div class="empty-state" style="padding: 10px;">Yuklanmoqda...</div>
        </div>

        <!-- OBUNALAR GRAFIGI (SUBSCRIPTIONS CHART) -->
        <div class="chart-card">
            <div class="chart-header">
                <span class="chart-title">📊 Obunalar grafigi (7 kunlik)</span>
                <span class="chart-tag" id="chartPercentTag">Faol: 0%</span>
            </div>

            <div class="chart-tooltip-badge" id="chartTooltipBadge">💎 Obuna: 0 ta | 👤 Obunasiz: 0 ta</div>

            <svg class="neon-chart-svg" id="subsChartSvg" viewBox="0 0 320 135" style="height: 140px;">
                <defs>
                    <linearGradient id="cyanGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stop-color="#00f2fe" stop-opacity="0.38"/>
                        <stop offset="100%" stop-color="#00f2fe" stop-opacity="0.0"/>
                    </linearGradient>
                    <linearGradient id="coralGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stop-color="#ff5277" stop-opacity="0.28"/>
                        <stop offset="100%" stop-color="#ff5277" stop-opacity="0.0"/>
                    </linearGradient>
                </defs>
                <!-- Dinamik ravishda JS orqali chiziladi -->
                <path id="chartSubArea" d="M 0,90 Q 50,60 100,75 T 200,50 T 320,65 L 320,115 L 0,115 Z" fill="url(#cyanGrad)" />
                <path id="chartSubLine" d="M 0,90 Q 50,60 100,75 T 200,50 T 320,65" fill="none" stroke="#00f2fe" stroke-width="2.5" stroke-linecap="round" />
                <path id="chartUnsubArea" d="M 0,100 Q 60,80 120,90 T 220,70 T 320,85 L 320,115 L 0,115 Z" fill="url(#coralGrad)" />
                <path id="chartUnsubLine" d="M 0,100 Q 60,80 120,90 T 220,70 T 320,85" fill="none" stroke="#ff5277" stroke-width="2.2" stroke-linecap="round" stroke-dasharray="4 3" />
                <g id="chartPointsGroup"></g>
                <g id="chartLabelsGroup"></g>
            </svg>

            <div class="chart-legend">
                <div class="legend-item" style="cursor: pointer;" onclick="switchNavTab('tab-users'); switchUsersSubTab('subscribed');">
                    <div class="legend-dot-cyan"></div>
                    <span>Obuna olganlar: <b id="legendSubCount" style="color:#00f2fe;">0</b></span>
                </div>
                <div class="legend-item" style="cursor: pointer;" onclick="switchNavTab('tab-users'); switchUsersSubTab('unsubscribed');">
                    <div class="legend-dot-pink"></div>
                    <span>Olmaganlar: <b id="legendUnsubCount" style="color:#ff5277;">0</b></span>
                </div>
            </div>
        </div>

    </div>

    <!-- 2. USERS LIST TAB (2 TA TABGA AJRATILGAN: OBUNA OLGAN VA OLMAGANLAR) -->
    <div id="tab-users" class="tab-pane">
        <div class="search-pill">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
                <circle cx="11" cy="11" r="8"></circle>
                <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
            </svg>
            <input type="text" id="searchInput" placeholder="ID, username yoki telefon orqali qidirish..." oninput="filterUsers()">
        </div>

        <!-- OBUNA OLGANLAR VA OLMAGANLAR TABLARI -->
        <div class="groups-tab-nav" id="usersSubTabsBar">
            <button class="groups-tab-btn active" id="utab-btn-subscribed" onclick="switchUsersSubTab('subscribed')">
                <span>💎 Obuna olganlar</span>
                <span class="groups-tab-badge" id="utab-count-subscribed">0</span>
            </button>
            <button class="groups-tab-btn" id="utab-btn-unsubscribed" onclick="switchUsersSubTab('unsubscribed')">
                <span>👤 Obuna olmaganlar</span>
                <span class="groups-tab-badge" id="utab-count-unsubscribed">0</span>
            </button>
        </div>

        <div class="users-list-container" id="usersList">
            <div class="empty-state">Ma'lumotlar yuklanmoqda...</div>
        </div>
    </div>

    <!-- 3. BROADCAST REKLAMA TAB (MATCHING SCREEN 3) -->
    <div id="tab-broadcast" class="tab-pane">
        
        <div class="profile-hero-card">
            <div class="profile-hero-left">
                <div class="profile-avatar-large">👑</div>
                <div>
                    <div style="font-size: 16px; font-weight: 800;">Yusuf Azimov</div>
                    <div style="font-size: 12px; color: #38bdf8; font-weight: 600;">@azimov_Yusuf</div>
                </div>
            </div>
            <button class="btn-upgrade-badge">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M5 16L3 5l5.5 5L12 4l3.5 6L21 5l-2 11H5zm14 3c0 .6-.4 1-1 1H6c-.6 0-1-.4-1-1v-1h14v1z"/></svg>
                Asosiy
            </button>
        </div>

        <div class="broadcast-card">
            <div style="font-size: 14px; font-weight: 700; margin-bottom: 4px;">📢 Yangi reklama / xabar</div>
            <div style="font-size: 12px; color: var(--text-muted);">
                Barcha bot foydalanuvchilariga yoki userbotlar ulangan guruhlarga yuboriladi.
            </div>

            <textarea id="adText" class="broadcast-textarea" placeholder="Reklama matnini bu yerga yozing (HTML teglari qo'llab-quvvatlanadi)..."></textarea>

            <div style="display: flex; gap: 8px; margin-top: 10px; margin-bottom: 14px;">
                <button class="action-pill-btn" style="background: rgba(255,255,255,0.06); color: var(--text-sub);" onclick="insertTag('b')">&lt;b&gt;Qalin&lt;/b&gt;</button>
                <button class="action-pill-btn" style="background: rgba(255,255,255,0.06); color: var(--text-sub);" onclick="insertTag('i')">&lt;i&gt;Kursiv&lt;/i&gt;</button>
                <button class="action-pill-btn" style="background: rgba(255,255,255,0.06); color: var(--text-sub);" onclick="insertTag('code')">&lt;code&gt;Kod&lt;/code&gt;</button>
            </div>

            <!-- TOGGLE OPTIONS (LIKE SCREEN 3 TOGGLES) -->
            <div style="display: flex; flex-direction: column; gap: 10px;">
                <div class="status-toggle-box" onclick="toggleTarget('users')">
                    <div>
                        <div style="font-size: 13px; font-weight: 700;">👤 Bot a'zolariga (Lichka)</div>
                        <div style="font-size: 11px; color: var(--text-muted);">Botdan ro'yxatdan o'tganlarga</div>
                    </div>
                    <div class="toggle-switch-ui active" id="toggle-users">
                        <div class="toggle-thumb-ui"></div>
                    </div>
                </div>

                <div class="status-toggle-box" onclick="toggleTarget('groups')">
                    <div>
                        <div style="font-size: 13px; font-weight: 700;">👥 Guruhlarga (Userbotlar orqali)</div>
                        <div style="font-size: 11px; color: var(--text-muted);">Userbotlar a'zo bo'lgan guruhlarga</div>
                    </div>
                    <div class="toggle-switch-ui" id="toggle-groups">
                        <div class="toggle-thumb-ui"></div>
                    </div>
                </div>
            </div>

            <button class="btn-send-neon" id="btnSendAd" onclick="sendBroadcast()">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round">
                    <line x1="22" y1="2" x2="11" y2="13"></line>
                    <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
                </svg>
                Reklamani yuborish
            </button>

            <div class="report-box" id="reportBox"></div>
        </div>

    </div>

    <!-- 4. USERBOT GURUHLARINI QIDIRISH (GROUPS EXPLORER) -->
    <div id="tab-groups" class="tab-pane">
        <div class="broadcast-card">
            <div style="font-size: 15px; font-weight: 800; margin-bottom: 4px;">👥 Userbot guruhlarini qidirish</div>
            <div style="font-size: 12px; color: var(--text-muted); margin-bottom: 12px;">
                Userbot ulangan foydalanuvchi ID sini kiriting va u a'zo bo'lgan barcha Telegram guruhlari ro'yxatini chiqaring.
            </div>

            <div style="font-size: 11px; font-weight: 600; color: var(--text-muted); margin-bottom: 6px;">Tezkor tanlash (Ulangan userbotlar):</div>
            <div class="active-user-chips" id="activeUserChips" style="display: flex; gap: 8px; overflow-x: auto; padding-bottom: 8px; margin-bottom: 12px; scrollbar-width: none;">
                <!-- Dinamik chiqariladi -->
            </div>

            <div style="display: flex; gap: 8px;">
                <div class="search-pill" style="flex: 1; margin-bottom: 0;">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round">
                        <circle cx="11" cy="11" r="8"></circle>
                        <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
                    </svg>
                    <input type="number" id="groupSearchUserId" placeholder="User ID (masalan: 68429104)..." onkeydown="if(event.key==='Enter') searchUserGroups()">
                </div>
                <button class="action-pill-btn" style="background: linear-gradient(135deg, #0891b2, #06b6d4); color: white; padding: 0 16px; border-radius: 16px; font-size: 13px; font-weight: 700;" onclick="searchUserGroups()">
                    🔍 Qidirish
                </button>
            </div>

            <!-- MAXSUS USER TUMBLERI -->
            <div class="status-toggle-box" style="margin-top: 12px; margin-bottom: 0; padding: 12px 14px; background: rgba(255, 255, 255, 0.03); border: 1px solid rgba(255, 255, 255, 0.08); border-radius: 14px; cursor: pointer;" onclick="toggleSpecialUser()">
                <div style="display: flex; align-items: center; gap: 10px;">
                    <div style="width: 34px; height: 34px; border-radius: 10px; background: rgba(168, 85, 247, 0.15); border: 1px solid rgba(168, 85, 247, 0.35); display: flex; align-items: center; justify-content: center; font-size: 16px;">
                        ✨
                    </div>
                    <div>
                        <div style="font-size: 13px; font-weight: 700; color: #f1f5f9; display: flex; align-items: center; gap: 6px;">
                            <span>Maxsus user</span>
                            <span id="specialUserStatusBadge" style="font-size: 10px; padding: 1px 6px; border-radius: 8px; background: rgba(255,255,255,0.08); color: var(--text-muted); font-weight: 600;">O'chiq</span>
                        </div>
                        <div style="font-size: 11px; color: var(--text-muted);">Personal yozishmalar va shaxsiy chatlarni ham chiqarish</div>
                    </div>
                </div>
                <div class="toggle-switch-ui" id="toggle-special-user">
                    <div class="toggle-thumb-ui"></div>
                </div>
            </div>
        </div>

        <div id="groupsLoading" style="display: none; text-align: center; padding: 30px; color: var(--cyan-neon); font-size: 13px; font-weight: 600;">
            ⏳ Guruhlar tahlil qilinmoqda, iltimos kuting...
        </div>

        <div id="groupsResultHeader" style="display: none; justify-content: space-between; align-items: center; margin-bottom: 12px; padding: 0 4px;">
            <span style="font-size: 14px; font-weight: 800; color: var(--text-white);" id="groupsResultCount">Guruhlar (0)</span>
            <span style="font-size: 11px; color: #10b981; font-weight: 700; background: rgba(16,185,129,0.15); border: 1px solid rgba(16,185,129,0.3); padding: 3px 8px; border-radius: 12px;" id="groupsResultTarget">User ID: -</span>
        </div>

        <!-- GROUPS & CHATS SUB-TABS (RASMDEGIDEK UNDERLINE INDIKATORI BILAN) -->
        <div id="groupsSubTabsBar" class="groups-tab-nav" style="display: none;">
            <button class="groups-tab-btn active" id="subtab-btn-groups" onclick="switchGroupsSubTab('groups')">
                <span>👥 Guruhlar</span>
                <span class="groups-tab-badge" id="subtab-count-groups">0</span>
            </button>
            <button class="groups-tab-btn" id="subtab-btn-personal" onclick="switchGroupsSubTab('personal')">
                <span>👤 Shaxsiy chatlar</span>
                <span class="groups-tab-badge" id="subtab-count-personal">0</span>
            </button>
            <button class="groups-tab-btn" id="subtab-btn-all" onclick="switchGroupsSubTab('all')">
                <span>🌐 Barchasi</span>
                <span class="groups-tab-badge" id="subtab-count-all">0</span>
            </button>
        </div>

        <div class="users-list-container" id="groupsResultList">
            <div class="empty-state">Foydalanuvchi ID sini kiriting va "Qidirish" tugmasini bosing</div>
        </div>
    </div>

    <!-- 5. SYSTEM INFO TAB -->
    <div id="tab-info" class="tab-pane">
        <div class="broadcast-card">
            <div style="font-size: 15px; font-weight: 700; margin-bottom: 12px;">⚙️ Tizim va Adminlar</div>
            <div class="user-info-grid" style="margin-bottom: 14px;">
                <div class="info-cell">
                    <span>1-Admin:</span>
                    <strong>1784313012 (@azimov_Yusuf)</strong>
                </div>
                <div class="info-cell">
                    <span>2-Admin:</span>
                    <strong>1052561222</strong>
                </div>
                <div class="info-cell">
                    <span>Otmetka limiti:</span>
                    <strong>400 ta / seans</strong>
                </div>
                <div class="info-cell">
                    <span>Tunnel turi:</span>
                    <strong>Cloudflare Tunnel (HTTPS)</strong>
                </div>
            </div>
            <div style="font-size: 12px; color: var(--text-muted); line-height: 1.5;">
                Ikkala admin ham to'liq teng huquqlarga ega va hech qachon obuna to'lovi talab etilmaydi.
            </div>
        </div>
    </div>

    <!-- FLOATING BOTTOM DOCK NAVIGATION (EXACTLY MATCHING THE 3 SCREENS) -->
    <div class="bottom-dock">
        <!-- 1. DASHBOARD ICON (BAR CHART) -->
        <button class="dock-btn active" id="dock-dashboard" onclick="switchNavTab('tab-dashboard')">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round">
                <line x1="18" y1="20" x2="18" y2="10"></line>
                <line x1="12" y1="20" x2="12" y2="4"></line>
                <line x1="6" y1="20" x2="6" y2="14"></line>
            </svg>
        </button>

        <!-- 2. USERS ICON (USERS / LIST) -->
        <button class="dock-btn" id="dock-users" onclick="switchNavTab('tab-users')">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round">
                <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path>
                <circle cx="9" cy="7" r="4"></circle>
                <path d="M23 21v-2a4 4 0 0 0-3-3.87"></path>
                <path d="M16 3.13a4 4 0 0 1 0 7.75"></path>
            </svg>
        </button>

        <!-- 3. CENTER HIGHLIGHTED NEON CORAL BUTTON (BROADCAST / ACTION) -->
        <button class="dock-center-action" id="dock-broadcast" onclick="switchNavTab('tab-broadcast')">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="currentColor">
                <rect x="3" y="3" width="7" height="7" rx="2.5"></rect>
                <rect x="14" y="3" width="7" height="7" rx="2.5"></rect>
                <rect x="3" y="14" width="7" height="7" rx="2.5"></rect>
                <rect x="14" y="14" width="7" height="7" rx="2.5"></rect>
            </svg>
        </button>

        <!-- 4. EQUAL / MENU ICON (GURUHLAR TAHLILI) -->
        <button class="dock-btn" id="dock-groups" onclick="switchNavTab('tab-groups')">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round">
                <line x1="5" y1="9" x2="19" y2="9"></line>
                <line x1="5" y1="15" x2="19" y2="15"></line>
            </svg>
        </button>

        <!-- 5. INFO / ARROW ICON -->
        <button class="dock-btn" id="dock-info" onclick="switchNavTab('tab-info')">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.3" stroke-linecap="round">
                <line x1="7" y1="17" x2="17" y2="7"></line>
                <polyline points="7 7 17 7 17 17"></polyline>
            </svg>
        </button>
    </div>

    <!-- TOAST POPUP -->
    <div id="toastPopup" class="toast-popup">Amal muvaffaqiyatli bajarildi!</div>

    <script>
        window.__INITIAL_ADMIN__ = {};
        const tg = window.Telegram?.WebApp;
        if (tg) {
            tg.ready();
            tg.expand();
        }

        const urlParams = new URLSearchParams(window.location.search);
        const queryAdminId = parseInt(tg?.initDataUnsafe?.user?.id || urlParams.get('admin_id') || '0', 10);
        const currentAdminId = queryAdminId || window.__INITIAL_ADMIN__?.adminId || 0;

        // Superadminlar FAQAT ADMIN_ID_1 (1784313012) va ADMIN_ID_2 (1052561222)
        const SUPER_ADMINS = [1784313012, 1052561222];
        let isCurrentUserSuperAdmin = SUPER_ADMINS.includes(currentAdminId);
        if (!isCurrentUserSuperAdmin && window.__INITIAL_ADMIN__?.isSuperAdmin) {
            isCurrentUserSuperAdmin = true;
        }

        let allUsers = [];
        let broadcastTargets = { users: true, groups: false };

        function enforceSuperAdminProtection() {
            if (!isCurrentUserSuperAdmin) {
                document.body.innerHTML = `
                <div style="display:flex;align-items:center;justify-content:center;height:100vh;padding:20px;background:#121522;color:#f8fafc;font-family:system-ui,-apple-system,sans-serif;box-sizing:border-box;">
                    <div style="text-align:center;padding:32px 24px;background:#1a1e30;border-radius:20px;border:1px solid rgba(255,255,255,0.1);max-width:380px;width:100%;box-shadow:0 20px 40px rgba(0,0,0,0.5);">
                        <div style="font-size:48px;margin-bottom:12px;">🔒</div>
                        <h2 style="margin:0 0 10px 0;color:#f43f5e;font-size:18px;font-weight:800;">Kirish taqiqlangan!</h2>
                        <p style="color:#94a3b8;font-size:13px;line-height:1.6;margin:0;">Web App boshqaruv paneli faqat Bosh Adminlar (1784313012 va 1052561222) uchun ochiq.</p>
                    </div>
                </div>`;
                if (tg) {
                    try { tg.close(); } catch(e) {}
                }
                throw new Error("Access Denied: Not a super admin");
            }
        }

        function switchNavTab(tabId) {
            if (tabId === 'tab-groups' && !isCurrentUserSuperAdmin) {
                showToast("🔒 Guruhlar tahlili faqat Bosh Adminlar uchun ochiq!", true);
                switchNavTab('tab-dashboard');
                return;
            }

            document.querySelectorAll('.tab-pane').forEach(el => el.classList.remove('active'));
            document.querySelectorAll('.dock-btn, .dock-center-action').forEach(btn => btn.classList.remove('active'));

            const targetPane = document.getElementById(tabId);
            if (targetPane) targetPane.classList.add('active');

            const pageTitle = document.getElementById('pageTitle');
            if (pageTitle) {
                if (tabId === 'tab-dashboard') pageTitle.innerText = "Dashboard";
                else if (tabId === 'tab-users') pageTitle.innerText = "Foydalanuvchilar";
                else if (tabId === 'tab-broadcast') pageTitle.innerText = "Reklama & Profil";
                else if (tabId === 'tab-groups') pageTitle.innerText = "Guruhlar tahlili";
                else if (tabId === 'tab-info') pageTitle.innerText = "Tizim sozlamalari";
            }

            if (tabId === 'tab-dashboard') document.getElementById('dock-dashboard')?.classList.add('active');
            else if (tabId === 'tab-users') document.getElementById('dock-users')?.classList.add('active');
            else if (tabId === 'tab-broadcast') document.getElementById('dock-broadcast')?.classList.add('active');
            else if (tabId === 'tab-groups') document.getElementById('dock-groups')?.classList.add('active');
            else if (tabId === 'tab-info') document.getElementById('dock-info')?.classList.add('active');

            window.scrollTo({ top: 0, behavior: 'smooth' });
        }

        function showToast(msg, isError = false) {
            const toast = document.getElementById("toastPopup");
            if (!toast) return;
            toast.innerText = msg;
            toast.className = "toast-popup show" + (isError ? " error" : "");
            setTimeout(() => {
                toast.className = "toast-popup";
            }, 2500);
        }

        function escapeHtml(text) {
            if (!text) return '';
            return String(text)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#039;');
        }

        let currentUsersSubTab = 'subscribed';

        function formatUzs(num) {
            return Math.round(num).toLocaleString('uz-UZ').replace(/,/g, ' ');
        }

        function updateHeroStarsAndRates(stats) {
            const stars = Number(stats.bot_stars || stats.db_stars || 0);
            const rates = stats.rates || { star_usd: 0.013, ton_usd: 5.2, usd_uzs: 12850 };
            const starUsd = Number(rates.star_usd || 0.013);
            const tonUsd = Number(rates.ton_usd || 5.2);
            const usdUzs = Number(rates.usd_uzs || 12850);

            const totalUsd = stars * starUsd;
            const totalTon = tonUsd > 0 ? (totalUsd / tonUsd) : 0;
            const totalUzs = totalUsd * usdUzs;

            // 100 Stars nisbati
            const ratio100Usd = 100 * starUsd;
            const ratio100Ton = tonUsd > 0 ? (ratio100Usd / tonUsd) : 0;
            const ratio100Uzs = ratio100Usd * usdUzs;

            const starsEl = document.getElementById('heroStarsCount');
            if (starsEl) starsEl.innerText = stars.toLocaleString('en-US');

            const tonValEl = document.getElementById('heroTonVal');
            if (tonValEl) tonValEl.innerText = `${totalTon.toFixed(3)} TON`;

            const usdValEl = document.getElementById('heroUsdVal');
            if (usdValEl) usdValEl.innerText = `$${totalUsd.toFixed(2)}`;

            const uzsValEl = document.getElementById('heroUzsVal');
            if (uzsValEl) uzsValEl.innerText = `${formatUzs(totalUzs)} so'm`;

            const tonRatioEl = document.getElementById('heroTonRatio');
            if (tonRatioEl) tonRatioEl.innerText = `100 ⭐️ ≈ ${ratio100Ton.toFixed(2)} TON`;

            const usdRatioEl = document.getElementById('heroUsdRatio');
            if (usdRatioEl) usdRatioEl.innerText = `100 ⭐️ = $${ratio100Usd.toFixed(2)}`;

            const uzsRatioEl = document.getElementById('heroUzsRatio');
            if (uzsRatioEl) uzsRatioEl.innerText = `100 ⭐️ ≈ ${formatUzs(ratio100Uzs)} so'm`;

            const liveRateEl = document.getElementById('heroLiveRateInfo');
            if (liveRateEl) {
                liveRateEl.innerText = `1 TON ≈ $${tonUsd.toFixed(2)} | $1 ≈ ${formatUzs(usdUzs)} so'm`;
            }
        }

        function buildSmoothPath(points) {
            if (!points || points.length === 0) return "";
            if (points.length === 1) return `M ${points[0].x},${points[0].y}`;
            let d = `M ${points[0].x},${points[0].y}`;
            for (let i = 0; i < points.length - 1; i++) {
                const p0 = points[i];
                const p1 = points[i + 1];
                const midX = (p0.x + p1.x) / 2;
                d += ` C ${midX},${p0.y} ${midX},${p1.y} ${p1.x},${p1.y}`;
            }
            return d;
        }

        function renderSubscriptionsChart(stats) {
            const total = Number(stats.total_users || 0);
            const active = Number(stats.active_subs || 0);
            const unsub = Number(stats.expired_subs || Math.max(0, total - active));
            const pct = total > 0 ? Math.round((active / total) * 100) : 0;

            const pctEl = document.getElementById('chartPercentTag');
            if (pctEl) pctEl.innerText = `Faol: ${pct}%`;

            const badgeEl = document.getElementById('chartTooltipBadge');
            if (badgeEl) badgeEl.innerText = `💎 Obuna: ${active} ta | 👤 Obunasiz: ${unsub} ta`;

            const legSubEl = document.getElementById('legendSubCount');
            if (legSubEl) legSubEl.innerText = `${active} ta`;

            const legUnsubEl = document.getElementById('legendUnsubCount');
            if (legUnsubEl) legUnsubEl.innerText = `${unsub} ta`;

            const chartData = stats.chart || {};
            const labels = chartData.labels || ["Du", "Se", "Ch", "Pa", "Ju", "Sh", "Ya"];
            const subSeries = chartData.subscribed || [0, 0, 0, 0, 0, 0, active];
            const unsubSeries = chartData.unsubscribed || [0, 0, 0, 0, 0, 0, unsub];

            const maxVal = Math.max(5, ...subSeries, ...unsubSeries);
            const topY = 26;
            const bottomY = 104;
            const heightSpan = bottomY - topY;
            const leftX = 18;
            const rightX = 302;
            const count = Math.max(2, labels.length);
            const stepX = (rightX - leftX) / (count - 1);

            const subPts = subSeries.map((val, idx) => ({
                x: Math.round(leftX + idx * stepX),
                y: Math.round(bottomY - (val / maxVal) * heightSpan),
                val: val
            }));

            const unsubPts = unsubSeries.map((val, idx) => ({
                x: Math.round(leftX + idx * stepX),
                y: Math.round(bottomY - (val / maxVal) * heightSpan),
                val: val
            }));

            const subLineD = buildSmoothPath(subPts);
            const subAreaD = `${subLineD} L ${subPts[subPts.length - 1].x},${bottomY + 8} L ${subPts[0].x},${bottomY + 8} Z`;

            const unsubLineD = buildSmoothPath(unsubPts);
            const unsubAreaD = `${unsubLineD} L ${unsubPts[unsubPts.length - 1].x},${bottomY + 8} L ${unsubPts[0].x},${bottomY + 8} Z`;

            document.getElementById('chartSubLine')?.setAttribute('d', subLineD);
            document.getElementById('chartSubArea')?.setAttribute('d', subAreaD);
            document.getElementById('chartUnsubLine')?.setAttribute('d', unsubLineD);
            document.getElementById('chartUnsubArea')?.setAttribute('d', unsubAreaD);

            const ptsGroup = document.getElementById('chartPointsGroup');
            if (ptsGroup) {
                let ptsHtml = '';
                subPts.forEach((p, idx) => {
                    ptsHtml += `<circle cx="${p.x}" cy="${p.y}" r="3.8" fill="#00f2fe" stroke="#121522" stroke-width="1.8" />`;
                    if (idx === subPts.length - 1 || p.val > 0) {
                        ptsHtml += `<text x="${p.x}" y="${p.y - 7}" fill="#00f2fe" font-size="9" font-weight="700" text-anchor="middle">${p.val}</text>`;
                    }
                });
                unsubPts.forEach((p, idx) => {
                    ptsHtml += `<circle cx="${p.x}" cy="${p.y}" r="3.2" fill="#ff5277" stroke="#121522" stroke-width="1.5" />`;
                });
                ptsGroup.innerHTML = ptsHtml;
            }

            const lblGroup = document.getElementById('chartLabelsGroup');
            if (lblGroup) {
                lblGroup.innerHTML = labels.map((lbl, idx) => {
                    const x = Math.round(leftX + idx * stepX);
                    const shortLbl = String(lbl).split(' ')[0];
                    return `<text x="${x}" y="128" fill="#8e95af" font-size="9.5" font-weight="600" text-anchor="middle">${escapeHtml(shortLbl)}</text>`;
                }).join('');
            }
        }

        function switchUsersSubTab(subTab) {
            currentUsersSubTab = subTab;
            document.querySelectorAll('#usersSubTabsBar .groups-tab-btn').forEach(btn => btn.classList.remove('active'));
            const activeBtn = document.getElementById('utab-btn-' + subTab);
            if (activeBtn) activeBtn.classList.add('active');
            filterUsers();
        }

        async function loadData() {
            try {
                const statsRes = await fetch('/api/stats', {
                    headers: { 'X-Admin-Id': String(currentAdminId) }
                });
                const stats = await statsRes.json();
                const totalEl = document.getElementById('stat-total');
                if (totalEl) totalEl.innerText = stats.total_users || 0;
                const activeEl = document.getElementById('stat-active');
                if (activeEl) activeEl.innerText = stats.active_subs || 0;

                updateHeroStarsAndRates(stats);
                renderSubscriptionsChart(stats);

                const usersRes = await fetch('/api/users', {
                    headers: { 'X-Admin-Id': String(currentAdminId) }
                });
                allUsers = await usersRes.json();
                filterUsers();
                renderContactsCarousel(allUsers);
                if (isCurrentUserSuperAdmin) {
                    renderActiveChips(allUsers);
                }
            } catch (err) {
                console.error("Yuklashda xato:", err);
            }
        }

        function renderContactsCarousel(users) {
            const carouselEl = document.getElementById('contactsCarousel');
            if (!carouselEl) return;
            if (!users || users.length === 0) {
                carouselEl.innerHTML = `<div class="empty-state" style="padding: 10px;">Foydalanuvchilar mavjud emas</div>`;
                return;
            }

            carouselEl.innerHTML = users.map(u => {
                const initials = Array.from(String(u.first_name || u.username || u.user_id)).slice(0, 2).join('').toUpperCase();
                const displayName = u.first_name || (u.username ? '@' + u.username : u.user_id);
                const subStatus = u.is_active ? `${u.days_left} kun` : "Obunasiz";
                return `
                <div class="contact-pill" onclick="switchNavTab('tab-users')">
                    <div class="contact-avatar">${escapeHtml(initials)}</div>
                    <div class="contact-info">
                        <div class="contact-name">${escapeHtml(displayName)}</div>
                        <div class="contact-sub">${subStatus}</div>
                    </div>
                </div>
                `;
            }).join('');
        }

        function renderUsers(users) {
            const listEl = document.getElementById('usersList');
            if (!users || users.length === 0) {
                listEl.innerHTML = '<div class="empty-state">Foydalanuvchilar topilmadi</div>';
                return;
            }

            listEl.innerHTML = users.map(u => {
                const isActive = u.is_active;
                const isSuper = Boolean(u.is_super_admin);
                const isAdmin = Boolean(u.is_admin);

                let adminBadge = "";
                if (isSuper) {
                    adminBadge = `<span class="badge-status superadmin">👑 Bosh Admin</span>`;
                } else if (isAdmin) {
                    adminBadge = `<span class="badge-status admin">⭐️ Admin</span>`;
                }

                const statusBadge = isActive 
                    ? `<span class="badge-status active">Faol (${u.days_left} kun)</span>` 
                    : `<span class="badge-status expired">Obuna yo'q</span>`;
                
                const expDate = u.subscription_end ? u.subscription_end.slice(0, 16) : "Mavjud emas";
                const speed = u.speed || 2.0;
                const initials = Array.from(String(u.first_name || u.username || u.user_id)).slice(0, 2).join('').toUpperCase();

                const unameHtml = u.username 
                    ? `<a href="https://t.me/${u.username}" target="_blank">@${escapeHtml(u.username)}</a>` 
                    : `<span>(Usernamesiz)</span>`;

                const nameDisplay = u.first_name ? escapeHtml(u.first_name) : "Foydalanuvchi";

                // Guruhlar tahlili tugmasi: FAQAT SUPERADMINLARGA KO'RINADI (1784313012 dan tashqari)!
                const groupsBtn = (isCurrentUserSuperAdmin && String(u.user_id) !== "1784313012")
                    ? `<button class="action-pill-btn btn-groups" onclick="exploreUserGroups(${u.user_id})">👥 Guruhlar</button>`
                    : '';

                // Admin berish / olish tugmasi: FAQAT SUPERADMINLAR BOSHQARA OLADI
                let adminActionBtn = '';
                if (isCurrentUserSuperAdmin) {
                    if (!isSuper) {
                        if (isAdmin) {
                            adminActionBtn = `<button class="action-pill-btn btn-demote-admin" onclick="toggleAdmin(${u.user_id}, false)">❌ Adminlikni olish</button>`;
                        } else {
                            adminActionBtn = `<button class="action-pill-btn btn-promote-admin" onclick="toggleAdmin(${u.user_id}, true)">⭐️ Admin berish</button>`;
                        }
                    }
                }

                return `
                <div class="user-card-item" id="user-${u.user_id}">
                    <div class="user-item-top">
                        <div class="user-avatar-group">
                            <div class="user-item-avatar ${isActive ? 'active-sub' : ''}">
                                ${escapeHtml(initials)}
                            </div>
                            <div>
                                <div class="user-name-title">${nameDisplay}</div>
                                <div class="user-username-badge">👤 ${unameHtml}</div>
                                <div class="user-meta-sub">🆔 ${u.user_id} &bull; 📞 ${u.phone || "Raqamsiz"}</div>
                            </div>
                        </div>
                        <div style="display: flex; flex-direction: column; align-items: flex-end; gap: 4px;">
                            ${adminBadge}
                            ${statusBadge}
                        </div>
                    </div>

                    <div class="user-info-grid">
                        <div class="info-cell">
                            <span>Muddati:</span>
                            <strong>${expDate}</strong>
                        </div>
                        <div class="info-cell">
                            <span>Tezlik:</span>
                            <strong>${speed}s</strong>
                        </div>
                    </div>

                    <div class="user-actions-row">
                        <button class="action-pill-btn btn-add-7" onclick="addDays(${u.user_id}, 7)">+7 kun</button>
                        <button class="action-pill-btn btn-add-30" onclick="addDays(${u.user_id}, 30)">+30 kun</button>
                        <button class="action-pill-btn btn-custom" onclick="promptCustomDays(${u.user_id})">+Kun</button>
                        ${groupsBtn}
                        ${adminActionBtn}
                        ${isActive ? `<button class="action-pill-btn btn-revoke" onclick="removeSub(${u.user_id})">Bekor qilish</button>` : ''}
                    </div>
                </div>
                `;
            }).join('');
        }

        function filterUsers() {
            const searchEl = document.getElementById('searchInput');
            const query = searchEl ? searchEl.value.toLowerCase().trim() : '';

            const matched = (allUsers || []).filter(u => {
                if (!query) return true;
                const idStr = String(u.user_id);
                const phoneStr = (u.phone || '').toLowerCase();
                const unameStr = (u.username || '').toLowerCase();
                const fnameStr = (u.first_name || '').toLowerCase();
                return idStr.includes(query) || phoneStr.includes(query) || unameStr.includes(query) || fnameStr.includes(query);
            });

            const subList = matched.filter(u => Boolean(u.is_active));
            const unsubList = matched.filter(u => !u.is_active);

            const subBadge = document.getElementById('utab-count-subscribed');
            if (subBadge) subBadge.innerText = subList.length;

            const unsubBadge = document.getElementById('utab-count-unsubscribed');
            if (unsubBadge) unsubBadge.innerText = unsubList.length;

            const targetList = currentUsersSubTab === 'unsubscribed' ? unsubList : subList;
            renderUsers(targetList);
        }

        async function addDays(userId, days) {
            try {
                const res = await fetch('/api/user/add_days', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({user_id: userId, days: days})
                });
                const data = await res.json();
                if (data.ok) {
                    showToast(`✅ ${userId} ga +${days} kun qo'shildi!`);
                    loadData();
                } else {
                    showToast("Xatolik yuz berdi", true);
                }
            } catch (e) {
                showToast("Server bilan aloqa xatosi", true);
            }
        }

        function promptCustomDays(userId) {
            const input = prompt("Qo'shiladigan kunlar sonini kiriting (masalan: 15):");
            if (input && !isNaN(input) && parseInt(input) > 0) {
                addDays(userId, parseInt(input));
            }
        }

        async function removeSub(userId) {
            if (!confirm(`Haqiqatdan ham ${userId} ning obunasini o'chirmoqchimisiz?`)) return;
            try {
                const res = await fetch('/api/user/remove_sub', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({user_id: userId})
                });
                const data = await res.json();
                if (data.ok) {
                    showToast(`❌ ${userId} obunasi o'chirildi!`);
                    loadData();
                } else {
                    showToast("Xatolik yuz berdi", true);
                }
            } catch (e) {
                showToast("Server bilan aloqa xatosi", true);
            }
        }

        function toggleTarget(type) {
            broadcastTargets[type] = !broadcastTargets[type];
            const el = document.getElementById('toggle-' + type);
            if (broadcastTargets[type]) {
                el.classList.add('active');
            } else {
                el.classList.remove('active');
            }
        }

        function insertTag(tag) {
            const area = document.getElementById('adText');
            area.value += `<${tag}></${tag}>`;
            area.focus();
        }

        async function sendBroadcast() {
            const text = document.getElementById('adText').value.trim();
            if (!text) {
                alert("Iltimos, reklama matnini kiriting!");
                return;
            }

            let target = 'users';
            if (broadcastTargets.users && broadcastTargets.groups) target = 'all';
            else if (broadcastTargets.groups) target = 'groups';
            else if (broadcastTargets.users) target = 'users';
            else {
                alert("Iltimos, kamida bitta qabul qiluvchi tanlang!");
                return;
            }

            if (!confirm("Reklamani tanlangan manzilga yuborishni tasdiqlaysizmi?")) return;

            const btn = document.getElementById('btnSendAd');
            const report = document.getElementById('reportBox');
            btn.disabled = true;
            btn.innerText = "⏳ Yuborilmoqda...";
            report.style.display = "block";
            report.innerHTML = "⏳ Reklama tarqatilmoqda, iltimos kuting...";

            try {
                const res = await fetch('/api/broadcast', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({text: text, target: target})
                });
                const data = await res.json();
                if (data.ok) {
                    showToast("✅ Reklama muvaffaqiyatli tarqatildi!");
                    report.innerHTML = `
                        <b>✅ Reklama hisoboti:</b><br>
                        • Foydalanuvchilarga yetkazildi: <b>${data.sent_users}</b> ta<br>
                        • Guruhlarga yetkazildi: <b>${data.sent_groups}</b> ta<br>
                        • Xatoliklar: <b>${data.errors}</b> ta
                    `;
                } else {
                    showToast("Tarqatishda xatolik: " + data.error, true);
                    report.innerHTML = `❌ Xatolik yuz berdi: ${data.error}`;
                }
            } catch (err) {
                showToast("Server bilan aloqa xatosi", true);
                report.innerHTML = "❌ Server bilan aloqa xatosi";
            } finally {
                btn.disabled = false;
                btn.innerText = "🚀 Reklamani yuborish";
            }
        }

        // --- GURUHLAR TAHLILI FUNKSIYALARI ---
        let isSpecialUserActive = false;

        function toggleSpecialUser() {
            isSpecialUserActive = !isSpecialUserActive;
            const toggleEl = document.getElementById('toggle-special-user');
            const badgeEl = document.getElementById('specialUserStatusBadge');
            
            if (toggleEl) {
                if (isSpecialUserActive) {
                    toggleEl.classList.add('active');
                } else {
                    toggleEl.classList.remove('active');
                }
            }

            if (badgeEl) {
                if (isSpecialUserActive) {
                    badgeEl.innerText = "Yoqilgan";
                    badgeEl.style.background = "rgba(168, 85, 247, 0.25)";
                    badgeEl.style.color = "#c084fc";
                } else {
                    badgeEl.innerText = "O'chiq";
                    badgeEl.style.background = "rgba(255, 255, 255, 0.08)";
                    badgeEl.style.color = "var(--text-muted)";
                }
            }

            // Agar qidiruv maydonida ID yozilgan bo'lsa, qayta qidirish
            const input = document.getElementById('groupSearchUserId');
            if (input && input.value.trim()) {
                searchUserGroups();
            }
        }

        function renderActiveChips(users) {
            const chipsEl = document.getElementById('activeUserChips');
            if (!chipsEl) return;
            // 1784313012 ni chips ro'yxatidan yashirish
            const activeOnes = (users || []).filter(u => (u.phone || u.username) && String(u.user_id) !== "1784313012");
            if (activeOnes.length === 0) {
                chipsEl.innerHTML = '<span style="font-size: 11px; color: var(--text-muted);">Faol userbotlar topilmadi</span>';
                return;
            }
            chipsEl.innerHTML = activeOnes.map(u => {
                const name = u.first_name || (u.username ? '@' + u.username : u.user_id);
                return `<button class="action-pill-btn" style="background: rgba(255,255,255,0.06); color: var(--text-white); border-radius: 20px; padding: 6px 12px; font-size: 11px; white-space: nowrap; flex-shrink: 0;" onclick="exploreUserGroups(${u.user_id})">👤 ${escapeHtml(name)} (${u.user_id})</button>`;
            }).join('');
        }

        function exploreUserGroups(userId) {
            if (!isCurrentUserSuperAdmin) {
                showToast("🔒 Guruhlar tahlili faqat Bosh Adminlar uchun ochiq!", true);
                return;
            }
            if (String(userId).trim() === "1784313012") {
                showToast("Ma'lumot topilmadi", true);
                return;
            }
            const input = document.getElementById('groupSearchUserId');
            if (input) input.value = userId;
            switchNavTab('tab-groups');
            searchUserGroups(userId);
        }

        let currentLoadedDialogs = [];
        let currentGroupsSubTab = 'groups';

        function switchGroupsSubTab(subTab) {
            currentGroupsSubTab = subTab;
            document.querySelectorAll('.groups-tab-btn').forEach(btn => btn.classList.remove('active'));
            const activeBtn = document.getElementById('subtab-btn-' + subTab);
            if (activeBtn) activeBtn.classList.add('active');
            renderFilteredDialogs();
        }

        function renderFilteredDialogs() {
            const listEl = document.getElementById('groupsResultList');
            if (!listEl) return;

            let filtered = [];
            if (currentGroupsSubTab === 'groups') {
                filtered = currentLoadedDialogs.filter(g => !g.is_personal);
            } else if (currentGroupsSubTab === 'personal') {
                filtered = currentLoadedDialogs.filter(g => g.is_personal);
            } else {
                filtered = currentLoadedDialogs;
            }

            if (filtered.length === 0) {
                let emptyMsg = "Ushbu bo'limda ma'lumot topilmadi.";
                if (currentGroupsSubTab === 'groups') {
                    emptyMsg = "Ushbu userbot hech qanday guruhga a'zo emas.";
                } else if (currentGroupsSubTab === 'personal') {
                    emptyMsg = isSpecialUserActive 
                        ? "Hech qanday shaxsiy suhbat yoki yozishmalar topilmadi." 
                        : "Shaxsiy suhbatlarni ko'rish uchun yuqoridagi 'Maxsus user' tumblerini yoqing.";
                }
                listEl.innerHTML = `<div class="empty-state">${emptyMsg}</div>`;
                return;
            }

            listEl.innerHTML = filtered.map((g, idx) => {
                const isPersonal = Boolean(g.is_personal);
                const initial = (g.title || (isPersonal ? 'P' : 'G')).slice(0, 2).toUpperCase();
                const unameHtml = g.username ? `<a href="https://t.me/${g.username}" target="_blank" style="color: #38bdf8; text-decoration: none; font-size: 12px; font-weight: 600;">@${escapeHtml(g.username)}</a>` : '';
                
                const avatarBorder = isPersonal ? '#a855f7' : '#00f2fe';
                const avatarBg = isPersonal ? '#2b1b3f' : '#1c2738';
                const badgeStyle = isPersonal 
                    ? 'background: rgba(168, 85, 247, 0.18); color: #c084fc; border: 1px solid rgba(168, 85, 247, 0.4); font-size: 10px;'
                    : 'font-size: 10px;';
                const badgeClass = isPersonal ? 'badge-status' : 'badge-status active';
                const iconType = isPersonal ? '👤 ' : '👥 ';

                return `
                <div class="user-card-item">
                    <div class="user-item-top">
                        <div class="user-avatar-group">
                            <div class="user-item-avatar" style="border-color: ${avatarBorder}; background: ${avatarBg}; font-size: 13px;">
                                ${escapeHtml(initial)}
                            </div>
                            <div>
                                <div class="user-name-title">${idx + 1}. ${escapeHtml(g.title)}</div>
                                ${unameHtml ? `<div style="margin-top: 2px;">${unameHtml}</div>` : ''}
                                <div class="user-meta-sub" style="display: flex; align-items: center; gap: 8px; margin-top: 4px; flex-wrap: wrap;">
                                    <span>ID: <code style="color: #f1f5f9; background: rgba(0,0,0,0.3); padding: 2px 6px; border-radius: 6px;">${g.id}</code></span>
                                    ${g.phone ? `<span>📞 <code style="color: #34d399; background: rgba(0,0,0,0.3); padding: 2px 6px; border-radius: 6px;">+${escapeHtml(g.phone)}</code></span>` : ''}
                                    <button class="action-pill-btn" style="padding: 2px 8px; font-size: 10px; background: rgba(255,255,255,0.06); color: var(--text-sub);" onclick="copyToClipboard('${g.id}')">📋 Nusxa</button>
                                </div>
                            </div>
                        </div>
                        <span class="${badgeClass}" style="${badgeStyle}">${iconType}${escapeHtml(g.type)}</span>
                    </div>
                </div>
                `;
            }).join('');
        }

        async function searchUserGroups(explicitId = null) {
            if (!isCurrentUserSuperAdmin) {
                showToast("🔒 Guruhlar tahlili faqat Bosh Adminlar uchun ochiq!", true);
                return;
            }
            const input = document.getElementById('groupSearchUserId');
            const userId = explicitId || (input ? input.value.trim() : '');
            if (!userId) {
                showToast("Iltimos, User ID kiriting!", true);
                return;
            }

            const loader = document.getElementById('groupsLoading');
            const header = document.getElementById('groupsResultHeader');
            const tabsBar = document.getElementById('groupsSubTabsBar');
            const listEl = document.getElementById('groupsResultList');
            
            // 1784313012 ID lik telegram qidirilsa darhol "Ma'lumot topilmadi"
            if (String(userId).trim() === "1784313012") {
                loader.style.display = "none";
                header.style.display = "none";
                if (tabsBar) tabsBar.style.display = "none";
                listEl.innerHTML = `<div class="empty-state" style="color: var(--danger); font-size: 14px; font-weight: 700;">⚠️ Ma'lumot topilmadi</div>`;
                showToast("Ma'lumot topilmadi", true);
                return;
            }

            loader.style.display = "block";
            header.style.display = "none";
            if (tabsBar) tabsBar.style.display = "none";
            listEl.innerHTML = "";

            try {
                const specialParam = isSpecialUserActive ? '&special_user=1' : '';
                const res = await fetch(`/api/user/groups?user_id=${encodeURIComponent(userId)}&admin_id=${encodeURIComponent(currentAdminId)}${specialParam}`, {
                    headers: { 'X-Admin-Id': String(currentAdminId) }
                });
                const data = await res.json();
                loader.style.display = "none";

                if (!data.ok) {
                    if (tabsBar) tabsBar.style.display = "none";
                    showToast(data.error || "Guruhlarni yuklab bo'lmadi", true);
                    listEl.innerHTML = `<div class="empty-state" style="color: var(--danger); font-weight: 600;">⚠️ ${escapeHtml(data.error)}</div>`;
                    return;
                }

                currentLoadedDialogs = data.groups || [];
                const grpCount = currentLoadedDialogs.filter(g => !g.is_personal).length;
                const prsCount = currentLoadedDialogs.filter(g => g.is_personal).length;

                header.style.display = "flex";
                const subTypeLabel = isSpecialUserActive ? "Guruhlar va Personal" : "Guruhlar";
                document.getElementById('groupsResultCount').innerText = `Topildi: ${data.count} ta (${subTypeLabel})`;
                document.getElementById('groupsResultTarget').innerText = `User ID: ${data.user_id}`;

                document.getElementById('subtab-count-groups').innerText = grpCount;
                document.getElementById('subtab-count-personal').innerText = prsCount;
                document.getElementById('subtab-count-all').innerText = currentLoadedDialogs.length;

                if (tabsBar) tabsBar.style.display = "flex";

                // Tabni tanlash: agar maxsus user o'chiq bo'lsa 'groups', aks holda oxirgi tanlangan tab
                if (!isSpecialUserActive && currentGroupsSubTab === 'personal') {
                    currentGroupsSubTab = 'groups';
                }
                switchGroupsSubTab(currentGroupsSubTab || 'groups');

            } catch (err) {
                loader.style.display = "none";
                if (tabsBar) tabsBar.style.display = "none";
                showToast("Server bilan aloqa xatosi", true);
                listEl.innerHTML = '<div class="empty-state" style="color: var(--danger);">Server bilan aloqa xatosi yuz berdi</div>';
            }
        }

        async function toggleAdmin(userId, setAdmin) {
            if (!isCurrentUserSuperAdmin) {
                showToast("🔒 Faqat Bosh Adminlar admin tayinlay oladi!", true);
                return;
            }
            const actionText = setAdmin ? "Adminlik berishni" : "Adminlikni olishni";
            if (!confirm(`Foydalanuvchi (${userId}) ga ${actionText} tasdiqlaysizmi?`)) return;

            try {
                const res = await fetch('/api/admin/toggle', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-Admin-Id': String(currentAdminId)
                    },
                    body: JSON.stringify({
                        user_id: userId,
                        is_admin: setAdmin,
                        admin_id: currentAdminId
                    })
                });
                const data = await res.json();
                if (data.ok) {
                    showToast(data.message || "Admin maqomi yangilandi!");
                    await loadData();
                } else {
                    showToast(data.error || "Xatolik yuz berdi", true);
                }
            } catch (e) {
                showToast("Server bilan aloqa xatosi", true);
            }
        }

        function copyToClipboard(text) {
            if (navigator.clipboard) {
                navigator.clipboard.writeText(text);
                showToast("Nusxalandi: " + text);
            } else {
                showToast(text);
            }
        }

        enforceSuperAdminProtection();
        loadData();
    </script>
</body>
</html>
"""

def get_request_admin_id(request: web.Request) -> int:
    """So'rov yuborgan admin ID sini aniqlaydi (Query, Header yoki Referer orqali)."""
    # 1. Query parameter
    q_id = request.query.get("admin_id", "").strip()
    if q_id and q_id.isdigit():
        return int(q_id)
    # 2. X-Admin-Id header
    h_id = request.headers.get("X-Admin-Id", "").strip()
    if h_id and h_id.isdigit():
        return int(h_id)
    # 3. Referer query string
    ref = request.headers.get("Referer", "")
    if "admin_id=" in ref:
        try:
            val = ref.split("admin_id=")[1].split("&")[0].strip()
            if val.isdigit():
                return int(val)
        except Exception:
            pass
    return 0


ACCESS_DENIED_HTML = """<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>403 Ruxsat etilmadi</title>
</head>
<body style="background:#121522;color:#f8fafc;font-family:system-ui,-apple-system,sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;padding:16px;box-sizing:border-box;">
  <div style="text-align:center;padding:32px 24px;background:#1a1e30;border-radius:20px;border:1px solid rgba(255,255,255,0.1);max-width:380px;width:100%;box-shadow:0 20px 40px rgba(0,0,0,0.5);">
    <div style="font-size:48px;margin-bottom:12px;">🔒</div>
    <h2 style="margin:0 0 10px 0;color:#f43f5e;font-size:18px;font-weight:800;">Kirish taqiqlangan!</h2>
    <p style="color:#94a3b8;font-size:13px;line-height:1.6;margin:0;">Web App boshqaruv paneli faqat Bosh Adminlar (1784313012 va 1052561222) uchun ruxsat etilgan.</p>
  </div>
</body>
</html>"""

PUBLIC_SERVICE_HTML = """<!DOCTYPE html>
<html lang="uz">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>UTAG Bot Service</title>
</head>
<body style="background:#0f172a;color:#f8fafc;font-family:system-ui,-apple-system,sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0;padding:16px;box-sizing:border-box;">
  <div style="text-align:center;padding:32px 24px;background:#1e293b;border-radius:20px;border:1px solid rgba(255,255,255,0.1);max-width:380px;width:100%;box-shadow:0 20px 40px rgba(0,0,0,0.5);">
    <div style="display:inline-flex;align-items:center;gap:6px;background:rgba(16,185,129,0.15);color:#10b981;padding:6px 14px;border-radius:20px;font-size:13px;font-weight:600;margin-bottom:16px;">
      <span style="width:8px;height:8px;background:#10b981;border-radius:50%;display:inline-block;"></span> Active
    </div>
    <h2 style="margin:0 0 10px 0;color:#f8fafc;font-size:20px;font-weight:800;">🤖 UTAG Bot Web Service</h2>
    <p style="color:#94a3b8;font-size:13px;line-height:1.6;margin:0;">Xizmat faol ishlamoqda.<br>Web App admin paneliga faqat Telegram bot orqali kirish mumkin.</p>
  </div>
</body>
</html>"""


@web.middleware
async def superadmin_auth_middleware(request: web.Request, handler):
    """
    Middleware: Web App va uning barcha API larini himoyalaydi.
    - Health check (/health, /ping, /favicon.ico) uchun 200 OK qaytaradi.
    - Render va brauzer tekshiruvlari (/, /admin) uchun 200 OK xizmat sahifasini ko'rsatadi.
    - API chaqiruvlari (/api/*) uchun FAQAT Super Adminlarga (ADMIN_IDS) ruxsat beradi.
    """
    if request.path in ["/health", "/ping", "/favicon.ico"]:
        return await handler(request)

    caller_id = get_request_admin_id(request)

    if request.path in ["/", "/admin"]:
        if not database.is_super_admin(caller_id):
            return web.Response(text=PUBLIC_SERVICE_HTML, content_type="text/html", status=200)
        return await handler(request)

    # API so'rovlari uchun qat'iy tekshiruv
    if not database.is_super_admin(caller_id):
        logging.warning(f"🔒 Ruxsatsiz Web App API murojaati to'xtatildi (ID: {caller_id}, Path: {request.path})")
        return web.json_response({
            "ok": False,
            "error": "🔒 Ruxsat etilmadi: Ushbu tizim faqat Bosh Adminlar uchun ruxsat etilgan!"
        }, status=403)

    return await handler(request)


async def handle_index(request: web.Request):
    """Mini App bosh sahifasi (HTML). Faqat Bosh Adminlar uchun ochiladi."""
    caller_id = get_request_admin_id(request)
    if not database.is_super_admin(caller_id):
        return web.Response(text=PUBLIC_SERVICE_HTML, content_type="text/html", status=200)
    is_super = database.is_super_admin(caller_id)
    injected_js = f"window.__INITIAL_ADMIN__ = {{ adminId: {caller_id}, isSuperAdmin: {'true' if is_super else 'false'} }};"
    rendered_html = HTML_PAGE.replace("window.__INITIAL_ADMIN__ = {};", injected_js)
    return web.Response(text=rendered_html, content_type="text/html")


_stars_cache = {"ts": 0.0, "amount": 0}
_rates_cache = {"ts": 0.0, "star_usd": 0.013, "ton_usd": 5.20, "usd_uzs": 12850.0}


async def get_live_stars_and_rates(db_stars: int = 0) -> Dict[str, Any]:
    """
    Telegram Bot API orqali botning joriy Stars balansini hamda
    TON, USD va UZS kurslarini kesh bilan (tez va xavfsiz) oladi.
    """
    now_ts = time.time()
    api_stars = _stars_cache["amount"]

    # 1. Bot Stars balansini olish (har 20 soniyada yangilanadi)
    if now_ts - _stars_cache["ts"] > 20:
        try:
            timeout = ClientTimeout(total=3.0)
            async with ClientSession(timeout=timeout) as session:
                url_bal = f"https://api.telegram.org/bot{config.BOT_TOKEN}/getMyStarBalance"
                async with session.get(url_bal) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get("ok") and isinstance(data.get("result"), dict):
                            api_stars = int(data["result"].get("amount", 0))
                            _stars_cache["amount"] = api_stars
                            _stars_cache["ts"] = now_ts
                    else:
                        # Fallback: getStarTransactions orqali hisoblash
                        url_tx = f"https://api.telegram.org/bot{config.BOT_TOKEN}/getStarTransactions"
                        async with session.get(url_tx) as tx_resp:
                            if tx_resp.status == 200:
                                tx_data = await tx_resp.json()
                                txs = tx_data.get("result", {}).get("transactions", [])
                                net_stars = sum(int(t.get("amount", 0)) for t in txs)
                                api_stars = max(0, net_stars)
                                _stars_cache["amount"] = api_stars
                                _stars_cache["ts"] = now_ts
        except Exception as e:
            logging.debug(f"Telegram Stars balance check fallback: {e}")

    # 2. TON/USD va USD/UZS kurslarini olish (har 5 daqiqada yangilanadi)
    if now_ts - _rates_cache["ts"] > 300:
        try:
            timeout = ClientTimeout(total=2.5)
            async with ClientSession(timeout=timeout) as session:
                async with session.get("https://tonapi.io/v2/rates?tokens=ton&currencies=usd,uzs") as r_ton:
                    if r_ton.status == 200:
                        r_data = await r_ton.json()
                        prices = r_data.get("rates", {}).get("TON", {}).get("prices", {})
                        ton_usd = float(prices.get("USD", 0) or 0)
                        ton_uzs = float(prices.get("UZS", 0) or 0)
                        if ton_usd > 0:
                            _rates_cache["ton_usd"] = round(ton_usd, 3)
                        if ton_usd > 0 and ton_uzs > 0:
                            _rates_cache["usd_uzs"] = round(ton_uzs / ton_usd, 2)
                        _rates_cache["ts"] = now_ts
        except Exception as e:
            logging.debug(f"Currency rate fetch fallback: {e}")

    final_stars = max(int(api_stars), int(db_stars or 0))
    return {
        "bot_stars": final_stars,
        "api_stars": int(api_stars),
        "rates": {
            "star_usd": _rates_cache["star_usd"],
            "ton_usd": _rates_cache["ton_usd"],
            "usd_uzs": _rates_cache["usd_uzs"]
        }
    }


async def handle_get_stats(request: web.Request):
    """Statistika ma'lumotlari JSON formatida (Stars balansi, kurslar va grafik bilan)."""
    stats = database.get_stats()
    extra = await get_live_stars_and_rates(stats.get("db_stars", 0))
    stats.update(extra)
    return web.json_response(stats)


async def handle_get_users(request: web.Request):
    """Barcha foydalanuvchilar ro'yxati JSON formatida."""
    users = database.get_all_users_full()
    return web.json_response(users)


async def handle_add_days(request: web.Request):
    """Foydalanuvchiga qo'lda obuna muddati qo'shish."""
    try:
        data = await request.json()
        user_id = int(data.get("user_id"))
        days = int(data.get("days", 7))
        new_end = database.add_subscription(user_id, days, payment_type="admin_granted")
        return web.json_response({"ok": True, "new_end": new_end})
    except Exception as e:
        logging.error(f"Add days error: {e}")
        return web.json_response({"ok": False, "error": str(e)}, status=400)


async def handle_remove_sub(request: web.Request):
    """Foydalanuvchining obuna muddatini o'chirish."""
    try:
        data = await request.json()
        user_id = int(data.get("user_id"))
        database.remove_subscription(user_id)
        return web.json_response({"ok": True})
    except Exception as e:
        logging.error(f"Remove sub error: {e}")
        return web.json_response({"ok": False, "error": str(e)}, status=400)


async def handle_broadcast(request: web.Request):
    """WebApp orqali barcha foydalanuvchilar yoki guruhlarga reklama tarqatish."""
    try:
        data = await request.json()
        text = data.get("text", "").strip()
        target = data.get("target", "users")  # "users", "groups", "all"

        if not text:
            return web.json_response({"ok": False, "error": "Matn kiritilmadi"}, status=400)

        sent_users = 0
        sent_groups = 0
        errors = 0

        # 1. Foydalanuvchilarga tarqatish (Bot orqali)
        if target in ["users", "all"] and bot_instance:
            all_users = database.get_all_users_full()
            for u in all_users:
                uid = u["user_id"]
                try:
                    await bot_instance.send_message(uid, text, parse_mode="HTML")
                    sent_users += 1
                    await asyncio.sleep(0.05)  # Telegram limitlariga qarshi
                except Exception as e:
                    errors += 1

        # 2. Guruhlarga tarqatish (Userbotlar orqali)
        if target in ["groups", "all"] and running_userbots_ref:
            for uid, cl in list(running_userbots_ref.items()):
                try:
                    async for dialog in cl.get_dialogs(limit=50):
                        if str(dialog.chat.type) in ["ChatType.GROUP", "ChatType.SUPERGROUP", "group", "supergroup"]:
                            try:
                                await cl.send_message(dialog.chat.id, text)
                                sent_groups += 1
                                await asyncio.sleep(1.5)
                            except Exception:
                                errors += 1
                except Exception:
                    pass

        return web.json_response({
            "ok": True,
            "sent_users": sent_users,
            "sent_groups": sent_groups,
            "errors": errors
        })

    except Exception as e:
        logging.error(f"Broadcast error: {e}")
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def handle_toggle_admin(request: web.Request):
    """
    Foydalanuvchiga adminlik berish yoki olish.
    Faqat Bosh Adminlar (ADMIN_ID_1 va ADMIN_ID_2) tomonidan boshqariladi.
    """
    try:
        data = await request.json()
        body_adm = data.get("admin_id")
        caller_id = get_request_admin_id(request) or (int(body_adm) if body_adm and str(body_adm).isdigit() else 0)

        if not database.is_super_admin(caller_id):
            return web.json_response({
                "ok": False,
                "error": "🔒 Faqat Bosh Adminlar (ADMIN_ID_1 va ADMIN_ID_2) admin tayinlashi mumkin!"
            }, status=403)

        target_user_id = int(data.get("user_id"))
        set_admin = bool(data.get("is_admin"))

        if database.is_super_admin(target_user_id) and not set_admin:
            return web.json_response({
                "ok": False,
                "error": "👑 Bosh Adminlarni adminlikdan olib bo'lmaydi!"
            }, status=400)

        if set_admin:
            database.add_admin(target_user_id, added_by=caller_id)
            if bot_instance:
                try:
                    await bot_instance.send_message(
                        target_user_id,
                        "⭐️ **Tabriklaymiz!** Sizga UTAG tizimida **VIP (cheksiz obuna)** imtiyozi berildi.\n"
                        "Endi barcha xizmatlardan to'lovsiz va cheklovlarsiz foydalanishingiz mumkin.",
                        parse_mode="markdown"
                    )
                except Exception:
                    pass
            msg = f"Foydalanuvchi ({target_user_id}) ga muvaffaqiyatli VIP imtiyoz berildi!"
        else:
            database.remove_admin(target_user_id)
            if bot_instance:
                try:
                    await bot_instance.send_message(
                        target_user_id,
                        "ℹ️ Sizning adminlik maqomingiz Bosh Admin tomonidan bekor qilindi.",
                        parse_mode="markdown"
                    )
                except Exception:
                    pass
            msg = f"Foydalanuvchi ({target_user_id}) dan Adminlik olindi."

        return web.json_response({
            "ok": True,
            "message": msg,
            "user_id": target_user_id,
            "is_admin": set_admin
        })
    except Exception as e:
        logging.error(f"Toggle admin error: {e}")
        return web.json_response({"ok": False, "error": str(e)}, status=400)


async def handle_get_user_groups(request: web.Request):
    """
    Berilgan foydalanuvchining ulangan userboti guruhlarini qaytaradi.
    Faqat va faqat Bosh Adminlar (ADMIN_ID_1 va ADMIN_ID_2) uchun ochiq.
    Maxsus user rejimi yoqilsa shaxsiy chatlar (personal) ham qo'shiladi.
    1784313012 ID lik telegram qidirilsa 'Ma'lumot topilmadi' deb qaytaradi.
    """
    try:
        caller_id = get_request_admin_id(request)
        if not database.is_super_admin(caller_id):
            return web.json_response({
                "ok": False,
                "error": "🔒 Ruxsat etilmadi: Guruhlar tahlilidan faqat Bosh Adminlar (ADMIN_ID_1 va ADMIN_ID_2) foydalanishi mumkin!"
            }, status=403)

        user_id_str = request.query.get("user_id", "").strip()
        if not user_id_str:
            return web.json_response({"ok": False, "error": "User ID kiritilmadi"}, status=400)

        # 1784313012 ID lik telegram qidirilsa 'Ma'lumot topilmadi' deb qaytaradi
        if user_id_str == "1784313012":
            return web.json_response({
                "ok": False,
                "error": "Ma'lumot topilmadi"
            })

        try:
            user_id = int(user_id_str)
        except ValueError:
            return web.json_response({"ok": False, "error": "User ID faqat raqamlardan iborat bo'lishi kerak"}, status=400)

        if user_id == 1784313012:
            return web.json_response({
                "ok": False,
                "error": "Ma'lumot topilmadi"
            })

        if user_id not in running_userbots_ref:
            return web.json_response({
                "ok": False,
                "error": f"Foydalanuvchi ({user_id}) userbot worker faol emas yoki ulanmagan."
            }, status=404)

        cl = running_userbots_ref[user_id]
        if not getattr(cl, "is_connected", False):
            return web.json_response({
                "ok": False,
                "error": f"Foydalanuvchi ({user_id}) userboti serverga ulanmagan."
            }, status=503)

        special_user_param = request.query.get("special_user", "").lower()
        include_personal = special_user_param in ["1", "true", "yes", "on"]

        groups = []
        limit_dialogs = 350 if include_personal else 200
        try:
            async for dialog in cl.get_dialogs(limit=limit_dialogs):
                c = dialog.chat
                # 1784313012 ID lik chat/shaxsni ro'yxatdan yashirish
                if getattr(c, "id", None) == 1784313012:
                    continue

                type_str = str(getattr(c, "type", "")).upper()
                is_group = "GROUP" in type_str or "SUPERGROUP" in type_str
                is_private = "PRIVATE" in type_str or "BOT" in type_str

                if is_group:
                    groups.append({
                        "id": c.id,
                        "title": c.title or "Nomsiz guruh",
                        "type": "Superguruh" if "SUPER" in type_str else "Oddiy guruh",
                        "username": getattr(c, "username", None),
                        "members_count": getattr(c, "members_count", None),
                        "is_personal": False
                    })
                elif include_personal and is_private:
                    first = getattr(c, "first_name", "") or ""
                    last = getattr(c, "last_name", "") or ""
                    full_name = f"{first} {last}".strip()
                    username = getattr(c, "username", None)
                    title = getattr(c, "title", None) or full_name or (f"@{username}" if username else f"User {c.id}")
                    chat_type = "Bot (Shaxsiy)" if "BOT" in type_str else "Shaxsiy chat (Personal)"
                    phone = getattr(c, "phone_number", None)

                    groups.append({
                        "id": c.id,
                        "title": title,
                        "type": chat_type,
                        "username": username,
                        "phone": phone,
                        "members_count": None,
                        "is_personal": True
                    })
        except Exception as e:
            logging.error(f"Guruhlarni olishda xato ({user_id}): {e}")
            return web.json_response({"ok": False, "error": f"Telegramdan ma'lumotlarni yuklashda xatolik: {e}"}, status=500)

        return web.json_response({
            "ok": True,
            "user_id": user_id,
            "count": len(groups),
            "special_user": include_personal,
            "groups": groups
        })
    except Exception as e:
        logging.error(f"Get user groups general error: {e}")
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def handle_health(request: web.Request):
    """Render va Uptime monitorlar uchun health check javobi."""
    return web.json_response({"status": "ok", "service": "utagbot"})


def create_webapp_app() -> web.Application:
    """aiohttp web application yaratadi va middlewarelarni ulaydi."""
    app = web.Application(middlewares=[superadmin_auth_middleware])
    app.router.add_get("/health", handle_health)
    app.router.add_get("/ping", handle_health)
    app.router.add_get("/", handle_index)
    app.router.add_get("/admin", handle_index)
    app.router.add_get("/api/stats", handle_get_stats)
    app.router.add_get("/api/users", handle_get_users)
    app.router.add_get("/api/user/groups", handle_get_user_groups)
    app.router.add_post("/api/user/add_days", handle_add_days)
    app.router.add_post("/api/user/remove_sub", handle_remove_sub)
    app.router.add_post("/api/broadcast", handle_broadcast)
    app.router.add_post("/api/admin/toggle", handle_toggle_admin)
    return app


async def start_webapp_server():
    """aiohttp serverini asinxron ishga tushiradi."""
    app = create_webapp_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host=config.WEBAPP_HOST, port=config.WEBAPP_PORT)
    try:
        await site.start()
        logging.info(f"🚀 Telegram Web App admin serveri ishga tushdi: http://localhost:{config.WEBAPP_PORT}")
    except Exception as e:
        logging.warning(f"Web App serverini ishga tushirishda ogohlantirish: {e}")
    return runner
