def yes_no_question(default=None):
    """
    Asks the user a yes/no question and translates it into bool.

    :return: bool
    """
    yes = {'yes', 'y', 'ye', 'Y'}
    no = {'no', 'n', 'N'}

    choice = input().lower().strip()
    if choice == '':
        choice = default
    if choice in yes:
        return True
    elif choice in no:
        return False
    else:
        print("Please respond with 'yes' or 'no'")


def get_user_input(validation_function, defaut=''):
    """
    Asks user for input and checks if it is valid by validating with
    validation function.

    :param: validation_function: function on which the user input is validated
        against
    :type validation_function: function
    :param defaut: default return value
    :type defaut: str
    :return: user input
    :rtype: str
    """

    while True:
        try:
            user_input = input()
            corrected_value = validation_function(user_input)
            if corrected_value:
                return corrected_value
            else:
                continue
        except Exception as e:
            raise e

