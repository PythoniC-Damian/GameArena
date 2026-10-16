"""Existing WTForms field and validation contracts."""
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField, SelectField, IntegerField, BooleanField, validators

class LocalizedForm(FlaskForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        from gamearena.i18n import translate
        for field in self:
            field.label.text = translate(field.label.text)


class RegistrationForm(LocalizedForm):
    username = StringField('Username', [
        validators.DataRequired(),
        validators.Length(min=3, max=150),
        validators.Regexp(r'^[a-zA-Z0-9_]+$', message="Username can only contain letters, numbers, and underscores")
    ])
    email = StringField('Email', [
        validators.DataRequired(),
        validators.Email(),
        validators.Length(max=150)
    ])
    password = PasswordField('Password', [
        validators.DataRequired(),
        validators.Length(min=6, message="Password must be at least 6 characters long")
    ])
    accept_terms = BooleanField('I agree to the Terms of Use and acknowledge the Privacy Policy', [validators.DataRequired(message='Please agree to the Terms of Use and acknowledge the Privacy Policy to create your account.')])
    submit = SubmitField('Create Account')


class LoginForm(LocalizedForm):
    email = StringField('Email', [
        validators.DataRequired(),
        validators.Email()
    ])
    password = PasswordField('Password', [validators.DataRequired()])
    submit = SubmitField('Login')


class EmailVerificationForm(LocalizedForm):
    email = StringField('Email', [
        validators.DataRequired(),
        validators.Email()
    ])
    code = StringField('Verification Code', [
        validators.DataRequired(),
        validators.Length(min=4, max=10)
    ])
    submit = SubmitField('Verify Email')


class ForgotPasswordForm(LocalizedForm):
    email = StringField('Email', [
        validators.DataRequired(),
        validators.Email()
    ])
    submit = SubmitField('Send Reset Code')


class ResetPasswordForm(LocalizedForm):
    email = StringField('Email', [
        validators.DataRequired(),
        validators.Email()
    ])
    code = StringField('Reset Code', [
        validators.DataRequired(),
        validators.Length(min=4, max=10)
    ])
    new_password = PasswordField('New Password', [
        validators.DataRequired(),
        validators.Length(min=6, message="Password must be at least 6 characters long")
    ])
    submit = SubmitField('Reset Password')


class TournamentForm(LocalizedForm):
    game = StringField('Game Name', [
        validators.DataRequired(),
        validators.Length(min=3, max=100)
    ])
    entry_fee = StringField('Entry Fee (GP)', [
        validators.DataRequired(),
        validators.Regexp(r'^\d+$', message="Entry fee must be a number")
    ])
    prize_pool = StringField('Prize Pool (GP)', [
        validators.DataRequired(),
        validators.Regexp(r'^\d+$', message="Prize pool must be a number")
    ])
    match_time = StringField('Match Time (YYYY-MM-DD HH:MM)', [
        validators.Optional(),
        validators.Length(max=50)
    ])
    max_participants = StringField('Max Participants', [
        validators.DataRequired(),
        validators.Regexp(r'^\d+$', message="Max participants must be a number")
    ])
    submit = SubmitField('Create Tournament')


class TournamentSetupForm(LocalizedForm):
    entry_fee = StringField('Entry Fee (GP)', [
        validators.DataRequired(),
        validators.Regexp(r'^\d+$', message="Entry fee must be a number")
    ])
    prize_pool = StringField('Prize Pool (GP)', [
        validators.DataRequired(),
        validators.Regexp(r'^\d+$', message="Prize pool must be a number")
    ])
    max_participants = StringField('Max Participants', [
        validators.DataRequired(),
        validators.Regexp(r'^\d+$', message="Max participants must be a number")
    ])
    room_id = StringField('Room ID', [
        validators.Optional(),
        validators.Length(max=50)
    ])
    room_password = StringField('Room Password', [
        validators.Optional(),
        validators.Length(max=100)
    ])
    match_time = StringField('Match Time (YYYY-MM-DD HH:MM)', [
        validators.Optional(),
        validators.Length(max=50)
    ])
    status = SelectField('Status', choices=[
        ('open', 'Open'),
        ('ongoing', 'Ongoing'),
        ('finished', 'Finished'),
        ('cancelled', 'Cancelled')
    ], default='open')
    first_place = StringField('1st Place', [
        validators.Optional(),
        validators.Length(max=150)
    ])
    second_place = StringField('2nd Place', [
        validators.Optional(),
        validators.Length(max=150)
    ])
    third_place = StringField('3rd Place', [
        validators.Optional(),
        validators.Length(max=150)
    ])
    submit = SubmitField('Save Tournament Setup')


class LeaderboardEntryForm(LocalizedForm):
    user_id = SelectField('Player', coerce=int, validators=[validators.DataRequired()])
    wins = IntegerField('Wins', [validators.DataRequired(), validators.NumberRange(min=0)])
    kills = IntegerField('Kills', [validators.DataRequired(), validators.NumberRange(min=0)])
    points = IntegerField('Points', [validators.DataRequired(), validators.NumberRange(min=0)])
    rank = IntegerField('Rank', [validators.DataRequired(), validators.NumberRange(min=1)])
    submit = SubmitField('Save Entry')

