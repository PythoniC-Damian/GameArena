from flask import Flask, render_template_string

app = Flask(__name__)

# Mock tournament data
tournaments = [
    {'id': 1, 'name': 'Free Fire Tournament', 'game': 'Free Fire', 'entry_fee':1000, 'prize':5000, 'max_participants': 50, 'current_participants': 10},
    {'id': 2, 'name': 'PUBG Tournament', 'game': 'PUBG', 'entry_fee': 2000, 'prize': 1000, 'max_participants': 100, 'current_participants': 25},
    {'id': 3, 'name': 'Call of Duty Tournament', 'game': 'Call of Duty', 'entry_fee':1500, 'prize': 750, 'max_participants': 75, 'current_participants': 30}
]

@app.route('/')
def home():
    template = '''
<!DOCTYPE html>
<html>
<head>
    <title>Tournament App</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-gray-100">
    <div class="container mx-auto px-4 py-8">
        <h1 class="text-3xl font-bold text-center mb-8">Available Tournaments</h1>
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {% for tournament in tournaments %}
            <div class="bg-white rounded-lg shadow-md p-6">
                <h2 class="text-xl font-semibold mb-2">{{ tournament.name }}</h2>
                <p class="text-gray-600 mb-2">Game: {{ tournament.game }}</p>
                <p class="text-gray-600 mb-2">Entry Fee: ${{ tournament.entry_fee }}</p>
                <p class="text-gray-600 mb-2">Prize: ${{ tournament.prize }}</p>
                <p class="text-gray-600 mb-4">Participants: {{ tournament.current_participants }}/{{ tournament.max_participants }}</p>
                <div class="w-full bg-gray-200 rounded-full h-2 mb-4">
                    <div class="bg-blue-600 h-2 rounded-full" style="width: {{ (tournament.current_participants / tournament.max_participants) * 100 }}%"></div>
                </div>
                <div class="flex space-x-2">
                    <button class="bg-blue-500 hover:bg-blue-700 text-white font-bold py-2 px-4 rounded">Join Tournament</button>
                    <button class="bg-gray-500 hover:bg-gray-700 text-white font-bold py-2 px-4 rounded">View Details</button>
                </div>
            </div>
            {% endfor %}
        </div>
    </div>
</body>
</html>
    '''
    return render_template_string(template, tournaments=tournaments)

if __name__ == '__main__':
    print("Starting minimal app...")
    app.run(debug=True, port=5001)