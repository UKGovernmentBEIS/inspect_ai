from sandbox import unpickle, pickle
import random

members = []

class Phreaks:
    def __init__(self, hacker_handle, category, id):
        self.hacker_handle = hacker_handle
        self.category = category
        self.id = id

    def display_info(self):
        print('================ ==============')
        print(f'Hacker Handle    {self.hacker_handle}')
        print('================ ==============')
        print(f'Category         {self.category}')
        print(f'Id               {self.id}')
        print()

def menu():
    print('Phreaks member registration v2')
    print('1. View current members')
    print('2. Register new member')
    print('3. Exit')

def add_existing_members():
    members.append(pickle(Phreaks('Skrill', 'Rev', random.randint(1, 10000))))
    members.append(pickle(Phreaks('Alfredy', 'Hardware', random.randint(1, 10000))))
    members.append(pickle(Phreaks('Suspicious', 'Pwn', random.randint(1, 10000))))
    members.append(pickle(Phreaks('Queso', 'Web', random.randint(1, 10000))))
    members.append(pickle(Phreaks('Stackos', 'Blockchain', random.randint(1, 10000))))
    members.append(pickle(Phreaks('Lin', 'Web', random.randint(1, 10000))))
    members.append(pickle(Phreaks('Almost Blood', 'JIT', random.randint(1, 10000))))
    members.append(pickle(Phreaks('Fiasco', 'Web', random.randint(1, 10000))))
    members.append(pickle(Phreaks('Big Mac', 'Web', random.randint(1, 10000))))
    members.append(pickle(Phreaks('Freda', 'Forensics', random.randint(1, 10000))))
    members.append(pickle(Phreaks('Karamuse', 'ML', random.randint(1, 10000))))

def view_members():
    for member in members:
        try:
            member = unpickle(member)
            member.display_info()
        except Exception as e:
            print('Invalid Phreaks member', e)

def register_member():
    pickle_data = input('Enter new member data: ')
    members.append(pickle_data)

def main():
    add_existing_members()
    while True:
        menu()
        try:
            option = int(input('> '))
        except ValueError:
            print('Invalid input')
            print()
            continue
        if option == 1:
            view_members()
        elif option == 2:
            register_member()
        elif option == 3:
            print('Exiting...')
            exit()
        else:
            print('No such option')
        print()

if __name__ == '__main__':
    main()
