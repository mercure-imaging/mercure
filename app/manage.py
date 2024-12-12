#!/usr/bin/env python
import test as mercure_test

import click
import webinterface.users as users


@click.group()
def manage():
    """
    Management commands for Mercure.
    """
    pass


@click.group()
def user():
    """User management commands."""
    pass


@click.command()
def test():
    """Test command to check the setup."""
    mercure_test.run_test()


@click.command()
@click.argument('username')
@click.option('--admin', is_flag=True, help='Make the user an admin.')
def add(username, admin: bool):
    """Add a new user."""
    if username in users.users_list:
        click.echo("User already exists.")
        return
    password_input = click.prompt("Enter password", hide_input=True, confirmation_prompt=True)
    users.users_list[username] = {"password": users.hash_password(password_input), "is_admin": "True" if admin else "False"}
    users.save_users()
    click.echo("User added successfully.")


@click.command()
def list():
    """List all users."""
    for user in users.users_list:
        click.echo(user)


@click.command()
@click.argument('username')
def delete(username):
    """Delete a user"""
    if username in users.users_list:
        del users.users_list[username]
        users.save_users()
        click.echo("User deleted.")
    else:
        click.echo("User does not exist.")


@click.command()
@click.argument('username')
def set_password(username):
    """Update a user's password"""
    user = users.users_list.get(username)
    if not user:
        click.echo("User does not exist.")
        return
    new_password = click.prompt("Enter the new password", hide_input=True, confirmation_prompt=True)
    user['password'] = users.hash_password(new_password)
    users.save_users()
    click.echo("Password updated successfully.")


# Adding commands to the user group
user.add_command(add)
user.add_command(delete)
user.add_command(list)
user.add_command(set_password)

# Adding the user group to the main CLI group
manage.add_command(user)
manage.add_command(test)
if __name__ == '__main__':
    users.logger.setLevel('ERROR')
    users.read_users()
    manage()
