import http.server
import socketserver
import urllib.parse
import json

PORT = 5000

# Simple global in-memory state to track progression
app_state = {
    "is_logged_in": False,
    "otp_sent": False,
    "phone": "",
    "step_1_subscribed": False,
    "step_2_subscribed": False, # offer 1400 @ 28 or more MBs
    "step_3_subscribed": False, # combo again
    "step_3_repurchased": False, # repurchase combo
    "step_4_subscribed": False, # offer 1400 @ 19
    "step_5_repurchased": False, # repurchase combo again
}

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
    <meta charset="UTF-8">
    <title>أنا فودافون - محاكاة الاختبار</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        body {{
            font-family: 'Outfit', 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: linear-gradient(135deg, #0f172a 0%, #1e1b4b 100%);
            color: #f8fafc;
            margin: 0;
            padding: 0;
            display: flex;
            flex-direction: column;
            align-items: center;
            min-height: 100vh;
        }}
        .header {{
            background-color: rgba(220, 38, 38, 0.9);
            width: 100%;
            padding: 15px 0;
            text-align: center;
            font-size: 24px;
            font-weight: 700;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
        }}
        .container {{
            max-width: 600px;
            width: 90%;
            background: rgba(30, 41, 59, 0.7);
            backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 20px;
            padding: 30px;
            margin-top: 50px;
            box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.3);
            text-align: center;
        }}
        h1 {{
            color: #ef4444;
            font-size: 28px;
            margin-bottom: 20px;
        }}
        p {{
            color: #94a3b8;
            font-size: 16px;
            line-height: 1.6;
        }}
        input[type="text"], input[type="password"] {{
            width: 80%;
            padding: 12px 20px;
            margin: 15px 0;
            border: 2px solid #334155;
            border-radius: 10px;
            background: #0f172a;
            color: white;
            font-size: 16px;
            transition: border-color 0.3s;
            text-align: center;
        }}
        input[type="text"]:focus {{
            border-color: #ef4444;
            outline: none;
        }}
        button, .btn {{
            background: linear-gradient(135deg, #ef4444 0%, #b91c1c 100%);
            color: white;
            border: none;
            padding: 12px 30px;
            font-size: 16px;
            font-weight: 600;
            border-radius: 10px;
            cursor: pointer;
            transition: all 0.3s;
            box-shadow: 0 4px 6px -1px rgba(239, 68, 68, 0.2);
            text-decoration: none;
            display: inline-block;
            margin: 10px;
        }}
        button:hover, .btn:hover {{
            transform: translateY(-2px);
            box-shadow: 0 10px 15px -3px rgba(239, 68, 68, 0.4);
        }}
        .card {{
            background: rgba(15, 23, 42, 0.6);
            border-radius: 15px;
            padding: 20px;
            margin: 20px 0;
            border: 1px dashed rgba(239, 68, 68, 0.3);
            text-align: right;
        }}
        .card h3 {{
            color: #f8fafc;
            margin-top: 0;
        }}
        .badge {{
            background-color: #10b981;
            color: white;
            padding: 4px 8px;
            border-radius: 5px;
            font-size: 12px;
            margin-right: 10px;
        }}
        .footer {{
            margin-top: auto;
            padding: 20px;
            font-size: 12px;
            color: #64748b;
        }}
    </style>
</head>
<body>
    <div class="header">Vodafone Egypt - بيئة محاكاة الاختبار</div>
    <div class="container">
        {content}
    </div>
    <div class="footer">أنا فودافون محاكاة © 2026 - لأغراض التطوير والاختبار المحلي فقط</div>
</body>
</html>
"""

class MockVodafoneHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format, *args):
        # Override to suppress output spam in terminal during bot run
        logger.info(format % args)

    def do_GET(self):
        url_parsed = urllib.parse.urlparse(self.path)
        path = url_parsed.path

        # Intercept action paths
        if path.startswith("/action/"):
            self.do_action()
            return

        # Handle reset endpoint
        if path == "/reset":
            for k in app_state:
                if type(app_state[k]) == bool:
                    app_state[k] = False
                else:
                    app_state[k] = ""
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "reset_success"}).encode("utf-8"))
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()

        html_content = ""

        # Router
        if path == "/ar/home":
            if not app_state["is_logged_in"]:
                if not app_state["otp_sent"]:
                    # Login Step 1: Input Phone
                    html_content = """
                    <h1>تسجيل الدخول إلى حسابك</h1>
                    <p>أدخل رقم هاتف فودافون لتلقي كلمة مرور مؤقتة (OTP):</p>
                    <form method="POST" action="/action/login-step1">
                        <input type="text" id="username" name="username" placeholder="رقم الهاتف (مثال: 01012345678)" required><br>
                        <button type="submit" id="get-otp">طلب كلمة المرور المؤقتة</button>
                    </form>
                    """
                else:
                    # Login Step 2: Input OTP
                    html_content = f"""
                    <h1>كود التحقق (OTP)</h1>
                    <p>تم إرسال كود التحقق إلى الرقم <b>{app_state['phone']}</b>.</p>
                    <form method="POST" action="/action/login-step2">
                        <input type="text" id="otp" name="otp" placeholder="أدخل الكود المكون من 6 أرقام" required><br>
                        <button type="submit">تأكيد ودخول</button>
                    </form>
                    """
            else:
                # Dashboard
                html_content = f"""
                <h1>مرحباً بك في أنا فودافون</h1>
                <p>الرقم الحالي: <b>{app_state['phone']}</b></p>
                <div style="margin-top: 30px;">
                    <a href="/ar/internet/plus" class="btn">باقات بلس كومبو (الويب)</a>
                    <a href="/ar/offers" class="btn">العروض اليومية (الموبايل)</a>
                    <a href="/ar/internet/management" class="btn">إدارة اشتراكاتي القادمة</a>
                </div>
                """

        elif path == "/ar/internet/plus":
            if not app_state["is_logged_in"]:
                html_content = "<h1>خطأ: يجب تسجيل الدخول أولاً!</h1><a href='/ar/home' class='btn'>دخول</a>"
            else:
                # Web Plus Packages
                status_text = "غير مشترك"
                button_html = '<a href="/action/subscribe-combo-step1" class="btn">اشترك</a>'
                
                if app_state["step_1_subscribed"] and not app_state["step_3_subscribed"]:
                    status_text = "مشترك (الخطوة 1)"
                    button_html = '<a href="/action/subscribe-combo-step3" class="btn">اشترك مرة أخرى</a>'
                elif app_state["step_3_subscribed"] and not app_state["step_3_repurchased"]:
                    status_text = "مشترك (الخطوة 3)"
                    button_html = '<a href="/action/repurchase-combo-step3" class="btn">إعادة شراء</a>'
                elif app_state["step_3_repurchased"] and not app_state["step_5_repurchased"]:
                    status_text = "مشترك ومجدد (الخطوة 3)"
                    button_html = '<a href="/action/repurchase-combo-step5" class="btn">إعادة شراء</a>'
                elif app_state["step_5_repurchased"]:
                    status_text = "مشترك ومجدد نهائي (الخطوة 5)"
                    button_html = '<span class="badge">مفعل</span>'

                html_content = f"""
                <h1>باقات فودافون بلس كومبو</h1>
                <p>تصفح واشترك في باقات الإنترنت المميزة لسطح المكتب.</p>
                
                <div class="card">
                    <h3>باقة بلس كومبو 600 <span class="badge">{status_text}</span></h3>
                    <p>سعة الباقة: 120,000 سوبر ميجا صالحة لمدة 30 يوم.</p>
                    <p>السعر الأساسي: 120 جنيه مصري.</p>
                    {button_html}
                </div>
                <a href="/ar/home" class="btn">الرجوع للرئيسية</a>
                """

        elif path == "/ar/offers":
            if not app_state["is_logged_in"]:
                html_content = "<h1>خطأ: يجب تسجيل الدخول أولاً!</h1>"
            else:
                # App Offers
                offer_html = ""
                if not app_state["step_1_subscribed"]:
                    offer_html = "<p>لا توجد عروض نشطة حالياً. يرجى الاشتراك في بلس كومبو أولاً.</p>"
                elif app_state["step_1_subscribed"] and not app_state["step_2_subscribed"]:
                    # Show Offer 1 (1400MB @ 28 EGP) or More Megabytes
                    offer_html = """
                    <div class="card">
                        <h3>عرض 1400 ميجابايت بـ28 جنيه بدلاً من 37</h3>
                        <p>احصل على سعة إنترنت إضافية مخفضة.</p>
                        <a href="/action/subscribe-offer28" class="btn">1400</a>
                    </div>
                    <div class="card">
                        <h3>عرض ميجابايتس أكتر على باقة 37 جنيه</h3>
                        <p>احصل على سعة مضاعفة عند تجديد باقة 37.</p>
                        <a href="/action/subscribe-more-mbs" class="btn">ميجابايتس أكتر</a>
                    </div>
                    """
                elif app_state["step_3_repurchased"] and not app_state["step_4_subscribed"]:
                    # Show Offer 2 (1400MB @ 19 EGP)
                    offer_html = """
                    <div class="card">
                        <h3>عرض 1400 ميجابايت بـ19 جنيه بدلاً من 37</h3>
                        <p>خصم رائع للخطوط المؤهلة.</p>
                        <a href="/action/subscribe-offer19" class="btn">19</a>
                    </div>
                    """
                else:
                    offer_html = "<p>لقد استخدمت العروض المؤهلة المتاحة لهذا اليوم.</p>"

                html_content = f"""
                <h1>عروض تطبيق أنا فودافون (الموبايل)</h1>
                <p>عروض خاصة وحصرية لخطك بناء على استهلاكك.</p>
                {offer_html}
                <a href="/ar/home" class="btn">الرجوع للرئيسية</a>
                """

        elif path == "/ar/internet/management":
            if not app_state["is_logged_in"]:
                html_content = "<h1>خطأ: يجب تسجيل الدخول أولاً!</h1>"
            else:
                price = "120 جنيه"
                if app_state["step_5_repurchased"]:
                    price = "19 جنيه"
                elif app_state["step_3_repurchased"]:
                    price = "28 جنيه"

                html_content = f"""
                <h1>إدارة الاشتراكات وباقات الإنترنت</h1>
                
                <div style="margin: 20px 0;">
                    <a href="#" class="btn" style="background:#334155;">الاشتراكات الحالية</a>
                    <a href="#" class="btn" id="upcoming-tab" style="background:#ef4444;">الاشتراكات القادمة</a>
                </div>

                <div class="card" id="upcoming-list">
                    <h3>باقة بلس كومبو 600 القادمة</h3>
                    <p>الحالة: <b>تنتظر التفعيل عند الشحن</b></p>
                    <p>تكلفة التفعيل المتوقعة: <b style="color:#10b981; font-size: 20px;">{price}</b></p>
                </div>
                <a href="/ar/home" class="btn">الرجوع للرئيسية</a>
                """
        else:
            self.send_response(404)
            self.wfile.write(b"Page Not Found")
            return

        formatted_html = HTML_TEMPLATE.format(content=html_content)
        self.wfile.write(formatted_html.encode("utf-8"))

    def do_POST(self):
        url_parsed = urllib.parse.urlparse(self.path)
        path = url_parsed.path

        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length).decode('utf-8')
        params = urllib.parse.parse_qs(post_data)

        # Process post actions
        if path == "/action/login-step1":
            phone = params.get("username", [""])[0]
            if phone:
                app_state["phone"] = phone
                app_state["otp_sent"] = True
            
        elif path == "/action/login-step2":
            otp = params.get("otp", [""])[0]
            if otp == "123456" or len(otp) == 6: # Accept 123456 or any 6 digit OTP for testing
                app_state["is_logged_in"] = True
                app_state["otp_sent"] = False

        self.send_response(303)
        self.send_header("Location", "/ar/home")
        self.end_headers()

    # We also intercept redirection routes for actions
    def do_action_redirect(self, next_state_key, redirect_url):
        app_state[next_state_key] = True
        self.send_response(303)
        self.send_header("Location", redirect_url)
        self.end_headers()

    def do_action(self):
        # Implement routing for custom link buttons
        path = self.path
        if path == "/action/subscribe-combo-step1":
            self.do_action_redirect("step_1_subscribed", "/ar/internet/plus")
        elif path == "/action/subscribe-offer28" or path == "/action/subscribe-more-mbs":
            self.do_action_redirect("step_2_subscribed", "/ar/offers")
        elif path == "/action/subscribe-combo-step3":
            self.do_action_redirect("step_3_subscribed", "/ar/internet/plus")
        elif path == "/action/repurchase-combo-step3":
            self.do_action_redirect("step_3_repurchased", "/ar/internet/plus")
        elif path == "/action/subscribe-offer19":
            self.do_action_redirect("step_4_subscribed", "/ar/offers")
        elif path == "/action/repurchase-combo-step5":
            self.do_action_redirect("step_5_repurchased", "/ar/internet/plus")
        else:
            self.send_response(404)
            self.end_headers()

def run_server():
    handler = MockVodafoneHandler
    # Allow address reuse
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), handler) as httpd:
        print(f"📡 Mock Vodafone Portal running at: http://localhost:{PORT}")
        httpd.serve_forever()

if __name__ == "__main__":
    run_server()
