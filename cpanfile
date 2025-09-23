requires 'String::Util';
requires 'IPC::System::Simple';

on 'build' => sub {
  requires 'App::FatPacker';
};
